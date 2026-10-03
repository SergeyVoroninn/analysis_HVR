"""
migrate_legacy_db.py — приведение устаревшей БД к актуальной схеме.

Зачем: старые БД (например `data/__ecg.db`) имеют другую схему:
  * ecg_records без колонок tp / updated_at / device_id / bio_* ;
  * athletes.birth_date почти всегда равен 2005-01-01 (фиктивное значение,
    которое проставлялось по умолчанию в старой версии диалога);
  * у записей может отсутствовать прибор.

Что делает скрипт:
  1. Читает из старой БД обязательный минимум — фамилию, имя и сырую ЭКГ.
  2. Переносит их в новую БД.
  3. Пересчитывает ВРС-метрики (RMSSD, ЧСС, статус, ИС, TP) по сырой ЭКГ
     через analysis.py — т.е. «остальное воспроизводится по ЭКГ».
  4. Проставляет прибор (device) по polar_id из шапки файла записи.
  5. Очищает фиктивные даты рождения (birth_date = None), т.к. по
     умолчанию дата больше не подставляется.

Безопасность: исходная БД не изменяется. Результат пишется в новую БД
(по умолчанию рядом с исходной с суффиксом _migrated).
"""
import argparse
import os
import re
import sys
import datetime

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from sqlalchemy import create_engine, text

from analysis import parse_rr, calc_metrics, calc_stress, compute_psd
from app_constants import ECG_PROFILES_YAML_PATH  # noqa: F401


LEGACY_ATHLETE_COLS = (
    "last_name", "first_name", "middle_name", "gender"
)
# Фальшивые значения даты рождения, которые подставлялись по умолчанию.
FAKE_BIRTH_DATES = {
    (2015, 1, 1), (2005, 1, 1), (2000, 1, 1), (1990, 1, 1), (1980, 1, 1),
}


# ----------------------------------------------------------------------
# Подключения
# ----------------------------------------------------------------------
class _Connection:
    def __init__(self, path):
        self.path = path
        self.engine = create_engine(f"sqlite:///{path}")


# ----------------------------------------------------------------------
# Чтение старой БД
# ----------------------------------------------------------------------
def _is_fake_birth(raw):
    """True, если birth_date — фиктивная («по умолчанию») дата."""
    if not raw:
        return True
    try:
        d = datetime.date.fromisoformat(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return True
    return (d.year, d.month, d.day) in FAKE_BIRTH_DATES


def read_legacy(db_path):
    """Читает старые таблицы и возвращает (athletes, records, raws).

    records: list[dict] с ключами athlete_id, recorded_at, duration_seconds.
    raws:    dict {record_id: raw_data}
    athletes может содержать birth_date в любом виде (str/date) — очистим ниже.
    """
    eng = create_engine(f"sqlite:///{db_path}")
    with eng.connect() as conn:
        has_raw = bool(
            conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ecg_raw'"
            )).fetchall()
        )

        athletes = [dict(r._mapping) for r in conn.execute(text(
            "SELECT * FROM athletes"
        ))]

        records = [dict(r._mapping) for r in conn.execute(text(
            "SELECT * FROM ecg_records"
        ))]

        raws = {}
        if has_raw:
            for r in conn.execute(text("SELECT record_id, raw_data FROM ecg_raw")):
                raws[r._mapping["record_id"]] = r._mapping["raw_data"]
        else:
            # Очень старые БД хранили raw_data прямо в ecg_records
            for r in conn.execute(text("SELECT id, raw_data FROM ecg_records")):
                rid = r._mapping["id"]
                if r._mapping["raw_data"]:
                    raws[rid] = r._mapping["raw_data"]
    return athletes, records, raws


# ----------------------------------------------------------------------
# Запись в новую БД
# ----------------------------------------------------------------------
def _parse_headers(raw):
    """Достаёт polar_id и datetime из шапки raw-записи."""
    polar, dt = None, None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("polar_id="):
            polar = line.split("=", 1)[1].strip() or None
        elif line.startswith("datetime="):
            dt = line.split("=", 1)[1].strip() or None
    return polar, dt


def write_migrated(out_path, athletes, records, raws):
    """Пересчитывает метрики и пишет новую БД с актуальной схемой."""
    from models import get_session, Athlete, ECGRecord, ECGRaw, Device

    if os.path.exists(out_path):
        os.remove(out_path)

    session = get_session(out_path)

    # Пол/имя — реальное значение (old: 'M'/'F' текст или bool-совместимое)
    def norm_gender(g):
        if g is None:
            return None
        if isinstance(g, str):
            return "M" if g.strip().upper() == "M" else "F"
        return "M" if g else "F"

    # Athlete
    athlete_id_map = {}
    try:
        for a in athletes:
            if _is_fake_birth(a.get("birth_date")):
                bd = None
            else:
                raw_bd = a.get("birth_date")
                bd = None
                if raw_bd:
                    try:
                        bd = datetime.date.fromisoformat(str(raw_bd))
                    except ValueError:
                        bd = None
            obj = Athlete(
                id=a["id"],
                last_name=a["last_name"],
                first_name=a["first_name"],
                middle_name=a.get("middle_name"),
                gender=norm_gender(a.get("gender")),
                birth_date=bd,          # пустая дата, если была фейком
                polar_id=a.get("polar_id"),
            )
            session.add(obj)
            athlete_id_map[a["id"]] = obj
        session.commit()

        # Device cache
        device_cache = {}

        added = 0
        for rec in records:
            rid = rec["id"]
            if rid not in raws:
                continue
            raw = raws[rid]
            aid = rec["athlete_id"]
            if aid not in athlete_id_map:
                continue

            polar, _ = _parse_headers(raw)

            rr = parse_rr(raw)
            m = calc_metrics(rr)
            s = calc_stress(rr)
            duration = rec.get("duration_seconds")
            if not duration and rr:
                duration = sum(rr) / 1000.0

            spectral_tp = None
            if rr:
                try:
                    _, _, bands = compute_psd(rr)
                    spectral_tp = bands.get("tp")
                except Exception:
                    spectral_tp = None

            # Прибор по polar_id (не выдумываем случайный id)
            device_id = None
            if polar:
                if polar not in device_cache:
                    dev = session.query(Device).filter(
                        Device.serial_number == polar).first()
                    if dev is None:
                        dev = Device(serial_number=polar)
                        session.add(dev)
                        session.flush()
                    device_cache[polar] = dev.id
                device_id = device_cache[polar]

            rec_obj = ECGRecord(
                athlete_id=aid,
                recorded_at=rec["recorded_at"],
                duration_seconds=duration,
                mean_hr=m["mean_hr"] if m else None,
                rmssd=m["rmssd"] if m else None,
                status=m["status"] if m else "ok",
                stress_si=s["si"] if s else None,
                tp=spectral_tp,
                device_id=device_id,
            )
            session.add(rec_obj)
            session.flush()
            session.add(ECGRaw(record_id=rec_obj.id, raw_data=raw))
            added += 1
            if added % 100 == 0:
                session.commit()
        session.commit()
        return added, len(athlete_id_map)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    # Поддерживаем эмодзи в консоли Windows (cp1251 не умеет их кодировать).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Миграция устаревшей БД в новую схему")
    parser.add_argument("db_path", help="Путь к старой БД (например data/__ecg.db)")
    parser.add_argument("--out", default=None,
                        help="Путь к новой БД (по умолчанию <имя>_migrated.db)")
    args = parser.parse_args()

    in_path = os.path.normpath(args.db_path)
    if not os.path.exists(in_path):
        print(f"❌ Файл не найден: {in_path}")
        sys.exit(1)

    out_path = args.out or re.sub(
        r"\.db$", "_migrated.db", in_path, flags=re.IGNORECASE)

    print(f"📥 Источник : {in_path}")
    print(f"📤 Результат: {out_path}")

    athletes, records, raws = read_legacy(in_path)
    print(f"Спортсменов: {len(athletes)}")
    print(f"Записей    : {len(records)}")
    print(f"С raw_data : {len(raws)}")

    n_rec, n_ath = write_migrated(out_path, athletes, records, raws)
    print(f"✅ Готово: {n_ath} атлетов, {n_rec} записей (метрики пересчитаны по ЭКГ).")


if __name__ == "__main__":
    main()