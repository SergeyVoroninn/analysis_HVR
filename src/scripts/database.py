"""
Единый менеджер базы данных для проекта анализа ВРС.

Предоставляет:
- Единое место определения схемы БД
- Автоматическое создание БД при первом запуске
- Единый интерфейс подключения для всех компонентов

Используется:
- prepare_database.py (создание тестовых данных)
- app.py (GUI просмотра)
- любыми другими скриптами
"""

import os
import sqlite3
from typing import Optional


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_RELATIVE = "../data/ecg.db"  # относительно scripts/


# ============================================================
# СХЕМА БАЗЫ ДАННЫХ (единое место определения)
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS athletes (
    id                  TEXT PRIMARY KEY,
    last_name           TEXT,
    first_name          TEXT,
    middle_name         TEXT,
    gender              TEXT,
    birth_date          DATE,
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
CREATE INDEX IF NOT EXISTS idx_ecg_cover2
    ON ecg_records(athlete_id, recorded_at, sdnn, status, stress_si);
"""

# ============================================================
# ПУТЬ К БАЗЕ ДАННЫХ
# ============================================================
def get_db_path(relative_path: Optional[str] = None) -> str:
    """
    Возвращает абсолютный путь к БД.
    
    :param relative_path: относительный путь (от scripts/) или None для дефолта
    :return: абсолютный путь к файлу БД
    """
    if relative_path is None:
        relative_path = DEFAULT_DB_RELATIVE
    
    if os.path.isabs(relative_path):
        return os.path.normpath(relative_path)
    
    return os.path.normpath(os.path.join(SCRIPTS_DIR, relative_path))


# ============================================================
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
# ============================================================
def init_database(db_path: Optional[str] = None, drop_existing: bool = False) -> str:
    """
    Инициализирует базу данных: создаёт файл и таблицы.
    
    :param db_path: путь к БД или None для дефолта
    :param drop_existing: если True, удаляет существующие таблицы
    :return: абсолютный путь к созданной БД
    """
    if db_path is None:
        db_path = get_db_path()
    
    # Создаём директорию если нужно
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    
    if drop_existing:
        conn.executescript("""
            DROP TABLE IF EXISTS ecg_records;
            DROP TABLE IF EXISTS athletes;
        """)
    
    conn.executescript(SCHEMA)
    conn.close()
    
    return db_path


# ============================================================
# ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# ============================================================
def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Возвращает подключение к БД, создавая её при необходимости.
    
    :param db_path: путь к БД или None для дефолта
    :return: sqlite3.Connection
    """
    if db_path is None:
        db_path = get_db_path()
    
    # Создаём БД если её нет
    if not os.path.exists(db_path):
        init_database(db_path)
    
    return sqlite3.connect(db_path)


# ============================================================
# УТИЛИТЫ
# ============================================================
def ensure_indexes(db_path: Optional[str] = None):
    """
    Создаёт индексы если их нет (для совместимости со старым кодом).
    Обычно не нужен — индексы создаются в SCHEMA.
    """
    if db_path is None:
        db_path = get_db_path()
    
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(ecg_records)")
    cols = {r[1] for r in cur.fetchall()}
    
    # Проверяем наличие колонок перед созданием составных индексов
    if {"athlete_id", "recorded_at", "sdnn", "status"} <= cols:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ecg_cover
            ON ecg_records(athlete_id, recorded_at, sdnn, status)
        """)
    
    if {"athlete_id", "recorded_at", "sdnn", "status", "stress_si"} <= cols:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ecg_cover2
            ON ecg_records(athlete_id, recorded_at, sdnn, status, stress_si)
        """)
    
    conn.commit()
    conn.close()