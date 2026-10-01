"""
test_migration.py — проверка идемпотентной миграции схемы к этапу 1:
- добавление колонок device_id / bio_similarity_pct в ecg_records;
- создание таблицы device;
- бэкфиллинг device_id из polar_id в ecg_raw.
"""
import sqlite3

from models import get_session, ECGRecord, Device


def _make_old_db(path):
    """Создаёт БД в schema до нововведений (без device_id/bio_similarity_pct/device)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE athletes (
            id VARCHAR PRIMARY KEY, last_name VARCHAR NOT NULL,
            first_name VARCHAR NOT NULL, middle_name VARCHAR,
            gender BOOLEAN, birth_date DATE, height_cm INTEGER, weight_kg FLOAT,
            resting_hr INTEGER, max_hr INTEGER, hrv_rmssd_baseline INTEGER,
            avg_rr_ms INTEGER, polar_id VARCHAR UNIQUE)
    """)
    cur.execute("""
        CREATE TABLE ecg_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL,
            duration_seconds FLOAT, updated_at DATETIME,
            mean_hr FLOAT, rmssd FLOAT, sdnn FLOAT, status VARCHAR,
            stress_si FLOAT, tp FLOAT)
    """)
    cur.execute("""
        CREATE TABLE ecg_raw (
            record_id INTEGER PRIMARY KEY, raw_data TEXT NOT NULL)
    """)
    cur.execute("INSERT INTO athletes (id,last_name,first_name,polar_id) VALUES (?,?,?,?)",
                ("a1", "Kazakov", "Filipp", "C8219D21"))
    cur.execute("INSERT INTO ecg_records (athlete_id, recorded_at) VALUES (?,?)",
                ("a1", "2026-08-20 09:15:18"))
    rid = cur.lastrowid
    raw = ("TeamLoggerH10Data\r\n[Header]\r\nversion=1.0\r\n"
           "datetime=2026.08.20 09:15:18\r\npolar_id=C8219D21\r\n[ECG]\r\n")
    cur.execute("INSERT INTO ecg_raw (record_id, raw_data) VALUES (?,?)", (rid, raw))
    conn.commit()
    conn.close()
    return rid


def _columns(db_path):
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ecg_records)")}
    conn.close()
    return cols


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    tbl = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    return tbl


def test_migration_adds_columns_and_backfills_device(tmp_path):
    db = str(tmp_path / "old.db")
    rid = _make_old_db(db)

    session = get_session(db)
    try:
        rec = session.get(ECGRecord, rid)
        assert rec.device_id is not None, "device_id должен быть проставлен из ecg_raw"
        dev = session.get(Device, rec.device_id)
        assert dev.serial_number == "C8219D21"
        assert dev.model == "Polar H10"
    finally:
        session.close()

    cols = _columns(db)
    assert {"device_id", "bio_similarity_pct"} <= cols, f"колонки не добавлены: {cols}"
    assert "sdnn" not in cols, "колонка sdnn должна быть удалена миграцией"
    assert "device" in _tables(db)


def test_migration_idempotent(tmp_path):
    db = str(tmp_path / "old2.db")
    rid = _make_old_db(db)

    get_session(db).close()
    get_session(db).close()  # повторный запуск не должен падать и дублировать

    session = get_session(db)
    try:
        assert session.query(ECGRecord).filter(ECGRecord.device_id.is_(None)).count() == 0
        devs = session.query(Device).all()
        assert len(devs) == 1, f"повторная миграция задвоила приборы: {len(devs)}"
    finally:
        session.close()


def test_fresh_db_has_columns_and_device_table(tmp_path):
    db = str(tmp_path / "new.db")
    get_session(db).close()

    cols = _columns(db)
    assert {"device_id", "bio_similarity_pct"} <= cols
    assert "sdnn" not in cols, "в свежей БД не должно быть колонки sdnn"
    assert "device" in _tables(db)