"""
Главный скрипт подготовки тестовой базы данных.

Импортирует:
  - athlete_generator  (create_athlete)
  - ecg_generator      (create_record)
  - schedule_engine    (build_schedules, load_config)
  - database           (get_connection, init_database, get_db_path)

Записывает всё в SQLite. Путь к БД задаётся в config.yaml.
"""

import os
import sqlite3
import random
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

from schedule_engine import build_schedules, load_config
from ecg_generator import create_record
from analysis import parse_rr, calc_metrics, calc_stress
from database import get_connection, init_database, get_db_path


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
        "db_path":          s.get("db_path", None),  # None = дефолт
        "store_raw_data":   s.get("store_raw_data", True),
        "seed":             s.get("seed", None),
    }


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================
def prepare_database(config_path="config.yaml"):
    """
    Генерирует данные и пишет их в SQLite.
    Путь к БД берётся из конфига (settings.db_path).
    """
    cfg = load_config(config_path)
    settings = _get_settings(cfg)

    if settings["seed"] is not None:
        random.seed(settings["seed"])

    duration  = settings["duration_seconds"]
    db_path   = get_db_path(settings["db_path"])
    store_raw = settings["store_raw_data"]

    # Инициализируем БД с удалением старых данных
    db_path = init_database(db_path, drop_existing=True)

    print("📋 Построение расписаний...")
    schedules = build_schedules(config_path)

    total_records = sum(len(times) for _, _, times in schedules)
    print(f"   Спортсменов: {len(schedules)} | Записей к генерации: {total_records}\n")

    conn = get_connection(db_path)

    processed = 0
    with conn:
        for athlete, profile_name, times in schedules:
            fio = f"{athlete['last_name']} {athlete['first_name']}"

            conn.execute(
                """INSERT INTO athletes
                   (id, last_name, first_name, middle_name, gender, birth_date,
                    height_cm, weight_kg, resting_hr, max_hr,
                    hrv_rmssd_baseline, avg_rr_ms, polar_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (athlete["id"], athlete["last_name"], athlete["first_name"],
                 athlete["middle_name"], athlete["gender"], athlete["birth_date"],
                 athlete["height_cm"], athlete["weight_kg"],
                 athlete["resting_hr"], athlete["max_hr"],
                 athlete["hrv_rmssd_baseline"], athlete["avg_rr_ms"],
                 athlete["polar_id"]),
            )

            rows = []
            for ts in times:
                dt_str = ts.strftime("%Y.%m.%d %H:%M:%S")
                raw_str = create_record(
                    device=athlete["polar_id"],
                    datetime_str=dt_str,
                    duration_seconds=duration,
                    mean_rr_ms=athlete["avg_rr_ms"],            # из профиля спортсмена
                    rmssd_ms=athlete["hrv_rmssd_baseline"],     # из профиля спортсмена
                )

                rr = parse_rr(raw_str)
                m = calc_metrics(rr)
                s = calc_stress(rr)
                raw = raw_str if store_raw else None

                rows.append((athlete["id"], ts.isoformat(sep=" "),
                             duration, profile_name, raw,
                             m["mean_hr"], m["rmssd"], m["sdnn"], m["status"],
                             s["si"] if s else None))

                processed += 1
                _progress_bar(processed, total_records, prefix="⚙️  Генерация ЭКГ", suffix=fio)

            conn.executemany(
                """INSERT INTO ecg_records
                   (athlete_id, recorded_at, duration_seconds, profile, raw_data,
                    mean_hr, rmssd, sdnn, status, stress_si)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    conn.close()
    print(f"\n✅ База: {db_path}")
    print(f"   Спортсменов: {len(schedules)}")
    print(f"   Записей ЭКГ: {total_records}")
    return db_path


# ============================================================
# ПРОВЕРКА БАЗЫ ДАННЫХ
# ============================================================
def verify_database(db_path):
    """Печатает сводку по содержимому базы."""
    if not os.path.exists(db_path):
        print(f"❌ Файл базы не найден: {db_path}")
        return

    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM athletes")
    print(f"\nСпортсменов: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM ecg_records")
    print(f"Записей ЭКГ: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT a.last_name, a.first_name, a.polar_id, e.profile, COUNT(e.id)
        FROM athletes a
        JOIN ecg_records e ON e.athlete_id = a.id
        GROUP BY a.id
        ORDER BY COUNT(e.id) DESC
    """)
    print(f"\n{'ФИО':22} | {'polar_id':8} | {'Профиль':22} | Записей")
    print("-" * 75)
    for last, first, pid, prof, cnt in cur.fetchall():
        print(f"{last} {first:12} | {pid:8} | {prof:22} | {cnt}")

    conn.close()


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
if __name__ == '__main__':
    db_path = prepare_database(CONFIG_PATH)
    verify_database(db_path)