"""Переносит raw_data из ecg_records в ecg_raw и сжимает БД."""
import sqlite3
import os
from database import get_db_path

db_path = get_db_path()
print(f"Миграция: {db_path}")
print(f"Размер до: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys=OFF")
cur = conn.cursor()

# 1. Создаём таблицу ecg_raw
cur.execute("""
    CREATE TABLE IF NOT EXISTS ecg_raw (
        record_id INTEGER PRIMARY KEY,
        raw_data TEXT NOT NULL,
        FOREIGN KEY (record_id) REFERENCES ecg_records(id) ON DELETE CASCADE
    )
""")

# 2. Переносим данные батчами по 100 записей (экономия RAM)
batch_size = 100
total = cur.execute("SELECT COUNT(*) FROM ecg_records WHERE raw_data IS NOT NULL").fetchone()[0]
print(f"Записей с raw_data: {total}")

offset = 0
moved = 0
while moved < total:
    rows = cur.execute("""
        SELECT id, raw_data FROM ecg_records
        WHERE raw_data IS NOT NULL
        LIMIT ? OFFSET ?
    """, (batch_size, offset)).fetchall()
    if not rows:
        break
    cur.executemany("INSERT OR IGNORE INTO ecg_raw (record_id, raw_data) VALUES (?, ?)", rows)
    ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(ids))
    cur.execute(f"UPDATE ecg_records SET raw_data = NULL WHERE id IN ({placeholders})", ids)
    conn.commit()
    moved += len(rows)
    print(f"  Перенесено: {moved}/{total}")

# 3. Удаляем колонку raw_data из ecg_records
cur.execute("ALTER TABLE ecg_records DROP COLUMN raw_data")
conn.commit()

# 4. Сжимаем БД (освобождает место на диске)
print("VACUUM...")
conn.execute("VACUUM")
conn.close()

print(f"Размер после: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")
print("✅ Готово")