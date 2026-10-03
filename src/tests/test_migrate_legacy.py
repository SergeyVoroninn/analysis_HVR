"""
test_migrate_legacy.py — проверка, что устаревшая схема БД открывается
новой версией без сбоя (авто-миграция в models._migrate) и что
migrate_legacy_db.py переносит данные и пересчитывает метрики.

История бага: старая БД имела ecg_records без колонок tp / updated_at /
device_id, app на ней падал.
"""
import datetime
import os
import sqlite3
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(SRC, "scripts")
for p in (SRC, SCRIPT):
    if p not in sys.path:
        sys.path.insert(0, p)

from models import get_session, Athlete, ECGRecord, ECGRaw, Device  # noqa: E402


def make_legacy_db(path):
    """Создаёт БД в самой старой схеме (без tp/updated_at/device, gender текст)."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("""
        CREATE TABLE athletes (
            id VARCHAR PRIMARY KEY, last_name VARCHAR NOT NULL,
            first_name VARCHAR NOT NULL, middle_name VARCHAR,
            gender VARCHAR, birth_date VARCHAR, height_cm INTEGER, weight_kg FLOAT,
            resting_hr INTEGER, max_hr INTEGER, hrv_rmssd_baseline INTEGER,
            avg_rr_ms INTEGER, polar_id VARCHAR UNIQUE)
    """)
    cur.execute("""
        CREATE TABLE ecg_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL,
            duration_seconds FLOAT, profile VARCHAR, mean_hr FLOAT, rmssd FLOAT,
            sdnn FLOAT, status VARCHAR, stress_si FLOAT)
    """)
    cur.execute("""
        CREATE TABLE ecg_raw (
            record_id INTEGER PRIMARY KEY, raw_data TEXT NOT NULL)
    """)
    # Атлет с фиктивной датой рождения (значение по умолчанию старого диалога)
    cur.execute("INSERT INTO athletes (id,last_name,first_name,birth_date,polar_id) VALUES (?,?,?,?,?)",
                ("a1", "Иванов", "Иван", "2005-01-01", "C8219D21"))
    raw = ("TeamLoggerH10Data\r\n[Header]\r\nversion=1.0\r\n"
           "datetime=2026.08.20 09:15:18\r\npolar_id=C8219D21\r\n[RR]\r\n"
           "900,910,895,905,912,898,906,903,899,908\r\n")
    cur.execute("INSERT INTO ecg_records (athlete_id, recorded_at) VALUES (?,?)",
                ("a1", "2026-08-20 09:15:18"))
    rid = cur.lastrowid
    cur.execute("INSERT INTO ecg_raw (record_id, raw_data) VALUES (?,?)", (rid, raw))
    conn.commit()
    conn.close()
    return rid


def test_legacy_db_opens_after_auto_migration(tmp_path):
    """Старая БД открывается без сбоя: _migrate добавляет недостающие колонки."""
    db = str(tmp_path / "legacy.db")
    make_legacy_db(db)

    session = get_session(db)  # не должно упасть
    try:
        assert session.query(ECGRecord).count() == 1
        # колонки tp/updated_at/device_id теперь доступны
        rec = session.query(ECGRecord).first()
        assert rec.tp is None or rec.tp is not None  # атрибут существует
        assert hasattr(rec, "tp") and hasattr(rec, "updated_at")
        # прибор подтянут из polar_id записи
        dev = session.query(Device).filter(Device.serial_number == "C8219D21").first()
        assert dev is not None, "прибор не создан из polar_id"
    finally:
        session.close()


def test_legacy_db_columns_added(tmp_path):
    """Проверка фактического наличия колонок после открытия."""
    db = str(tmp_path / "legacy2.db")
    make_legacy_db(db)
    get_session(db).close()

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ecg_records)")}
    conn.close()
    assert {"tp", "updated_at", "device_id"} <= cols, f"не хватает колонок: {cols}"
    assert "sdnn" not in cols, "sdnn должна удаляться"
    assert "profile" not in cols, "profile должна удаляться"


def test_legacy_db_backfills_tp_after_migration(tmp_path):
    """Старая БД без готовых метрик: после открытия TP/метрики пересчитываются по ЭКГ."""
    db = str(tmp_path / "legacy3.db")
    make_legacy_db(db)

    session = get_session(db)  # авто-миграция + бэкфилл метрик
    try:
        rec = session.query(ECGRecord).first()
        assert rec.tp is not None, "TP должен пересчитаться по сырой ЭКГ"
        assert rec.tp > 0
        assert rec.rmssd is not None and rec.rmssd > 0
        assert rec.stress_si is not None
        assert rec.mean_hr is not None
        # запись с [RR] из нашего тестового raw должна дать осмысленные числа
        assert 40 <= rec.mean_hr <= 100
    finally:
        session.close()

    conn = sqlite3.connect(db)
    nulls = conn.execute("SELECT COUNT(*) FROM ecg_records WHERE tp IS NULL").fetchone()[0]
    conn.close()
    assert nulls == 0, "не должно остаться записей без TP"