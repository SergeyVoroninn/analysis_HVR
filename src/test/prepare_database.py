"""
Главный скрипт подготовки тестовой базы данных.

Импортирует:
  - athlete_generator  (create_athlete)
  - ecg_generator      (create_record)
  - schedule_engine    (build_schedules, load_config)

Записывает всё в SQLite.
"""

import os
import sqlite3
import random
import sys

from athlete_generator import create_athlete
from ecg_generator import create_record
from schedule_engine import build_schedules, load_config
from analysis import parse_rr, calc_metrics, calc_stress


# ============================================================
# ПРОГРЕСС-БАР (без внешних зависимостей)
# ============================================================
def _progress_bar(current, total, prefix="", suffix="", length=40):
    """
    Рисует ASCII-прогресс-бар в одну строку.

    :param current: текущее значение
    :param total:   итоговое значение
    :param prefix:  текст слева
    :param suffix:  текст справа
    :param length:  ширина полосы в символах
    """
    percent = current / total if total > 0 else 1.0
    filled = int(length * percent)
    bar = '█' * filled + '░' * (length - filled)
    line = f"\r{prefix} |{bar}| {percent * 100:5.1f}% {suffix}"
    sys.stdout.write(line)
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


# ============================================================
# СХЕМА БАЗЫ ДАННЫХ
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS athletes (
    id                  TEXT PRIMARY KEY,
    last_name           TEXT,
    first_name          TEXT,
    middle_name         TEXT,
    gender              TEXT,
    birth_year          INTEGER,
    age                 INTEGER,
    height_cm           INTEGER,
    weight_kg           REAL,
    resting_hr          INTEGER,
    max_hr              INTEGER,
    hrv_rmssd_baseline  INTEGER,
    avg_rr_ms           INTEGER,
    polar_id            TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS ecg_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id        TEXT NOT NULL,
    recorded_at       TEXT NOT NULL,
    duration_seconds  REAL,
    profile           TEXT,
    raw_data          TEXT,
    mean_hr           REAL,
    rmssd             REAL,
    sdnn              REAL,
    status            TEXT,
    stress_si         REAL,
    created_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (athlete_id) REFERENCES athletes(id)
);

CREATE INDEX IF NOT EXISTS idx_ecg_athlete ON ecg_records(athlete_id);
CREATE INDEX IF NOT EXISTS idx_ecg_time    ON ecg_records(recorded_at);
CREATE INDEX IF NOT EXISTS idx_ecg_cover
    ON ecg_records(athlete_id, recorded_at, sdnn, status);
"""


# ============================================================
# НАСТРОЙКИ
# ============================================================
def _get_settings(cfg):
    s = cfg.get("settings", {})
    return {
        "duration_seconds": s.get("duration_seconds", 12.0),
        "db_path":          s.get("db_path", "data/ecg.db"),
        "store_raw_data":   s.get("store_raw_data", True),
        "seed":             s.get("seed", None),
    }


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ: ПОДГОТОВКА БАЗЫ ДАННЫХ
# ============================================================
def prepare_database(config_path="config.yaml"):
    """
    Генерирует данные и пишет их в SQLite.

    1. Загружает конфиг.
    2. Строит расписания для команды.
    3. Генерирует ЭКГ для каждой записи.
    4. Записывает в базу данных.
    """
    cfg = load_config(config_path)
    settings = _get_settings(cfg)

    # Фиксируем зерно для воспроизводимости
    if settings["seed"] is not None:
        random.seed(settings["seed"])

    duration  = settings["duration_seconds"]
    db_path   = settings["db_path"]
    store_raw = settings["store_raw_data"]

    # Создаём папку для базы
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    # Строим расписания (уже содержит спортсменов из конфига)
    print("📋 Построение расписаний...")
    schedules = build_schedules(config_path)

    # Считаем общее число записей для прогресс-бара
    total_records = sum(len(times) for _, _, times in schedules)
    print(f"   Спортсменов: {len(schedules)} | Записей к генерации: {total_records}\n")

    conn = sqlite3.connect(db_path)
    
    # Удаляем старые таблицы и создаём заново с актуальной схемой
    conn.executescript("""
        DROP TABLE IF EXISTS ecg_records;
        DROP TABLE IF EXISTS athletes;
    """)
    conn.executescript(SCHEMA)

    processed = 0
    with conn:  # единая транзакция
        for athlete, profile_name, times in schedules:
            fio = f"{athlete['last_name']} {athlete['first_name']}"

            # Вставляем спортсмена
            conn.execute(
                """INSERT INTO athletes
                   (id, last_name, first_name, middle_name, gender, birth_year,
                    age, height_cm, weight_kg, resting_hr, max_hr,
                    hrv_rmssd_baseline, avg_rr_ms, polar_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (athlete["id"], athlete["last_name"], athlete["first_name"],
                 athlete["middle_name"], athlete["gender"], athlete["birth_year"],
                 athlete["age"], athlete["height_cm"], athlete["weight_kg"],
                 athlete["resting_hr"], athlete["max_hr"],
                 athlete["hrv_rmssd_baseline"], athlete["avg_rr_ms"],
                 athlete["polar_id"]),
            )

            # Готовим записи ЭКГ с прогресс-баром
            rows = []
            for ts in times:
                dt_str = ts.strftime("%Y.%m.%d %H:%M:%S")
                raw_str = create_record(device=athlete["polar_id"],
                                        datetime_str=dt_str,
                                        duration_seconds=duration)

                rr = parse_rr(raw_str)
                m = calc_metrics(rr)
                s = calc_stress(rr)
                raw = raw_str if store_raw else None

                # Ровно 10 значений под 10 колонок INSERT
                rows.append((athlete["id"], ts.isoformat(sep=" "),
                             duration, profile_name, raw,
                             m["mean_hr"], m["rmssd"], m["sdnn"], m["status"],
                             s["si"] if s else None))

                processed += 1
                _progress_bar(processed, total_records,
                              prefix="⚙️  Генерация ЭКГ",
                              suffix=f"({processed}/{total_records}) {fio}")

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
def verify_database(db_path="data/ecg.db"):
    """Печатает сводку по содержимому базы."""
    if not os.path.exists(db_path):
        print(f"❌ Файл базы не найден: {db_path}")
        return

    conn = sqlite3.connect(db_path)
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
    prepare_database("config.yaml")
    verify_database("data/ecg.db")