"""
Главный скрипт подготовки тестовой базы данных.
Записывает всё в SQLite через SQLAlchemy. Путь к БД задаётся в config.yaml.
"""
import argparse
import os
import random
import sys
import shutil

from sqlalchemy import insert, func

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

SRC_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, SRC_DIR)

from schedule_engine import build_schedules, load_config
from ecg_generator import create_record
from analysis import parse_rr, calc_metrics, calc_stress
from database import get_db_path
from models import get_session, Athlete, ECGRecord, ECGRaw


# ============================================================
# ПРОГРЕСС-БАР
# ============================================================
def _progress_bar(current, total, prefix="", suffix="", length=30):
    if total <= 0:
        return
    cols = shutil.get_terminal_size((120, 24)).columns
    percent = 100.0 * current / total
    filled = int(length * current // total)
    bar = "█" * filled + "░" * (length - filled)
    counter = f"({current}/{total})"
    fixed = len(prefix) + length + len(counter) + 10
    suffix = suffix[: max(0, cols - fixed - 2)]
    line = f"\r{prefix} |{bar}| {percent:5.1f}% {counter} {suffix}"

    if sys.stdout.isatty():
        sys.stdout.write(line)
        sys.stdout.flush()
        if current >= total:
            sys.stdout.write("\n")
            sys.stdout.flush()
    else:
        step = max(1, total // 20)
        if current % step == 0 or current == total:
            print(line.lstrip("\r"))


# ============================================================
# ЧТЕНИЕ НАСТРОЕК
# ============================================================
def _get_settings(cfg):
    s = cfg.get("settings", {})
    return {
        "duration_seconds": s.get("duration_seconds", 12.0),
        "db_path":          s.get("db_path", None),
        "store_raw_data":   s.get("store_raw_data", True),
        "seed":             s.get("seed", None),
    }


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================
def prepare_database(config_path="config.yaml"):
    cfg = load_config(config_path)
    settings = _get_settings(cfg)

    if settings["seed"] is not None:
        random.seed(settings["seed"])

    duration  = settings["duration_seconds"]
    db_path   = get_db_path(settings["db_path"])
    store_raw = settings["store_raw_data"]

    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑  Удалена старая база: {db_path}")

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    print("📋 Построение расписаний...")
    schedules = build_schedules(config_path)

    total_records = sum(len(times) for _, _, times in schedules)
    print(f"   Спортсменов: {len(schedules)} | Записей к генерации: {total_records}\n")

    session = get_session(db_path)
    try:
        # --- Спортсмены (один батч) ---
        athletes_data = [
            {
                "id":                  athlete["id"],
                "last_name":           athlete["last_name"],
                "first_name":          athlete["first_name"],
                "middle_name":         athlete["middle_name"],
                "gender":              athlete["gender"],
                "birth_date":          athlete["birth_date"],
                "height_cm":           athlete["height_cm"],
                "weight_kg":           athlete["weight_kg"],
                "resting_hr":          athlete["resting_hr"],
                "max_hr":              athlete["max_hr"],
                "hrv_rmssd_baseline":  athlete["hrv_rmssd_baseline"],
                "avg_rr_ms":           athlete["avg_rr_ms"],
                "polar_id":            athlete["polar_id"],
            }
            for athlete, _, _ in schedules
        ]
        if athletes_data:
            session.execute(insert(Athlete), athletes_data)
            session.commit()
            print(f"✅ Спортсменов сохранено: {len(athletes_data)}")

        # --- ЭКГ: по одной (нужен id для связи с ECGRaw) ---
        processed = 0

        for athlete, profile_name, times in schedules:
            fio = f"{athlete['last_name']} {athlete['first_name']}"

            for ts in times:
                dt_str = ts.strftime("%Y.%m.%d %H:%M:%S")
                raw_str = create_record(
                    device=athlete["polar_id"],
                    datetime_str=dt_str,
                    duration_seconds=duration,
                    mean_rr_ms=athlete["avg_rr_ms"],
                    rmssd_ms=athlete["hrv_rmssd_baseline"],
                )

                rr = parse_rr(raw_str)
                m = calc_metrics(rr)
                s = calc_stress(rr)

                # 1) Создаём лёгкую запись (без raw)
                rec = ECGRecord(
                    athlete_id=athlete["id"],
                    recorded_at=ts.isoformat(sep=" "),
                    duration_seconds=duration,
                    profile=profile_name,
                    mean_hr=m["mean_hr"],
                    rmssd=m["rmssd"],
                    sdnn=m["sdnn"],
                    status=m["status"],
                    stress_si=s["si"] if s else None,
                )
                session.add(rec)
                session.flush()  # ← получаем rec.id

                # 2) Если нужно — сохраняем raw в отдельной таблице
                if store_raw and raw_str:
                    raw = ECGRaw(record_id=rec.id, raw_data=raw_str)
                    session.add(raw)

                session.commit()

                processed += 1
                _progress_bar(processed, total_records,
                              prefix="⚙️  Генерация ЭКГ", suffix=fio)

    except Exception as e:
        session.rollback()
        print(f"\n❌ Ошибка при генерации БД: {e}")
        raise
    finally:
        session.close()

    print(f"\n✅ База: {db_path}")
    print(f"   Спортсменов: {len(schedules)}")
    print(f"   Записей ЭКГ: {total_records}")
    if store_raw:
        print(f"   Raw данные:   в отдельной таблице ecg_raw")
    else:
        print(f"   Raw данные:   НЕ сохранялись")
    return db_path


# ============================================================
# ПРОВЕРКА БАЗЫ ДАННЫХ
# ============================================================
def verify_database(db_path):
    if not os.path.exists(db_path):
        print(f"❌ Файл базы не найден: {db_path}")
        return

    session = get_session(db_path)
    try:
        athletes_count = session.query(func.count(Athlete.id)).scalar()
        records_count = session.query(func.count(ECGRecord.id)).scalar()
        raw_count = session.query(func.count(ECGRaw.record_id)).scalar()

        print(f"\nСпортсменов: {athletes_count}")
        print(f"Записей ЭКГ: {records_count}")
        print(f"С raw_data:  {raw_count}")

        from sqlalchemy.orm import aliased
        AthleteAlias = aliased(Athlete)

        rows = (
            session.query(
                AthleteAlias.last_name,
                AthleteAlias.first_name,
                AthleteAlias.polar_id,
                ECGRecord.profile,
                func.count(ECGRecord.id).label("cnt"),
                func.avg(ECGRecord.rmssd).label("avg_rmssd"),
                func.avg(ECGRecord.stress_si).label("avg_si"),
            )
            .join(ECGRecord, ECGRecord.athlete_id == AthleteAlias.id)
            .group_by(AthleteAlias.id, ECGRecord.profile)
            .order_by(func.count(ECGRecord.id).desc())
            .all()
        )

        print(f"\n{'ФИО':22} | {'polar_id':8} | {'Профиль':15} | Зап | RMSSD |  ИС")
        print("-" * 90)
        for last, first, pid, prof, cnt, rmssd, si in rows:
            print(f"{last} {first:12} | {pid:8} | {prof or '':15} | "
                  f"{cnt:3} | {rmssd or 0:5.0f} | {si or 0:3.0f}")

    finally:
        session.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Подготовка тестовой БД")
    parser.add_argument("--config", default=CONFIG_PATH,
                        help="Путь к YAML-конфигу (по умолчанию config.yaml в папке scripts/)")
    args = parser.parse_args()
    db_path = prepare_database(args.config)
    verify_database(db_path)