"""
Главный скрипт подготовки тестовой базы данных.

Импортирует:
  - athlete_generator  (create_athlete)
  - ecg_generator      (create_record)
  - schedule_engine    (build_schedules, load_config)
  - models             (ORM-модели и сессия)

Записывает всё в SQLite через SQLAlchemy. Путь к БД задаётся в config.yaml.
"""

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
from models import get_session, Athlete, ECGRecord, Base


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
    """
    Генерирует данные и пишет их в SQLite через ORM.
    Путь к БД берётся из конфига (settings.db_path).
    """
    cfg = load_config(config_path)
    settings = _get_settings(cfg)

    if settings["seed"] is not None:
        random.seed(settings["seed"])

    duration  = settings["duration_seconds"]
    db_path   = get_db_path(settings["db_path"])
    store_raw = settings["store_raw_data"]

    # Удаляем старую БД, чтобы создать чистую
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑  Удалена старая база: {db_path}")

    # Создаём директорию если нужно
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    print("📋 Построение расписаний...")
    schedules = build_schedules(config_path)

    total_records = sum(len(times) for _, _, times in schedules)
    print(f"   Спортсменов: {len(schedules)} | Записей к генерации: {total_records}\n")

    session = get_session(db_path)
    try:
        # --- Массовая вставка спортсменов (один батч) ---
        athletes_data = []
        for athlete, profile_name, times in schedules:
            athletes_data.append({
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
            })

        if athletes_data:
            session.execute(insert(Athlete), athletes_data)
            session.commit()
            print(f"✅ Спортсменов сохранено: {len(athletes_data)}")

        # --- Генерация и массовая вставка ЭКГ (батчами по 100 записей) ---
        processed = 0
        BATCH_SIZE = 100
        records_batch = []

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
                raw = raw_str if store_raw else None

                records_batch.append({
                    "athlete_id":       athlete["id"],
                    "recorded_at":      ts.isoformat(sep=" "),
                    "duration_seconds": duration,
                    "profile":          profile_name,
                    "raw_data":         raw,
                    "mean_hr":          m["mean_hr"],
                    "rmssd":            m["rmssd"],
                    "sdnn":             m["sdnn"],
                    "status":           m["status"],
                    "stress_si":        s["si"] if s else None,
                })

                processed += 1
                _progress_bar(processed, total_records,
                              prefix="⚙️  Генерация ЭКГ", suffix=fio)

                # Сбрасываем батч в БД
                if len(records_batch) >= BATCH_SIZE:
                    session.execute(insert(ECGRecord), records_batch)
                    session.commit()
                    records_batch.clear()

        # Остаток батча
        if records_batch:
            session.execute(insert(ECGRecord), records_batch)
            session.commit()

    except Exception as e:
        session.rollback()
        print(f"\n❌ Ошибка при генерации БД: {e}")
        raise
    finally:
        session.close()

    print(f"\n✅ База: {db_path}")
    print(f"   Спортсменов: {len(schedules)}")
    print(f"   Записей ЭКГ: {total_records}")
    return db_path


# ============================================================
# ПРОВЕРКА БАЗЫ ДАННЫХ
# ============================================================
def verify_database(db_path):
    """Печатает сводку по содержимому базы (ORM-версия)."""
    if not os.path.exists(db_path):
        print(f"❌ Файл базы не найден: {db_path}")
        return

    session = get_session(db_path)
    try:
        athletes_count = session.query(func.count(Athlete.id)).scalar()
        records_count = session.query(func.count(ECGRecord.id)).scalar()
        print(f"\nСпортсменов: {athletes_count}")
        print(f"Записей ЭКГ: {records_count}")

        # Сводка по спортсменам
        from sqlalchemy.orm import aliased
        AthleteAlias = aliased(Athlete)

        rows = (
            session.query(
                AthleteAlias.last_name,
                AthleteAlias.first_name,
                AthleteAlias.polar_id,
                ECGRecord.profile,
                func.count(ECGRecord.id).label("cnt"),
            )
            .join(ECGRecord, ECGRecord.athlete_id == AthleteAlias.id)
            .group_by(AthleteAlias.id, ECGRecord.profile)
            .order_by(func.count(ECGRecord.id).desc())
            .all()
        )

        print(f"\n{'ФИО':22} | {'polar_id':8} | {'Профиль':22} | Записей")
        print("-" * 75)
        for last, first, pid, prof, cnt in rows:
            print(f"{last} {first:12} | {pid:8} | {prof or '':22} | {cnt}")

    finally:
        session.close()


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
if __name__ == '__main__':
    db_path = prepare_database(CONFIG_PATH)
    verify_database(db_path)