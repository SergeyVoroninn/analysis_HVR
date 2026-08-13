"""Быстрая диагностика БД — без полного сканирования raw_data."""
import os
import sqlite3
from database import get_db_path

db_path = get_db_path()
size_mb = os.path.getsize(db_path) / 1048576
print(f"База: {db_path}")
print(f"Размер файла: {size_mb:.1f} MB\n")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("=== Спортсмены ===")
for row in cur.execute("""SELECT last_name, first_name, hrv_rmssd_baseline, avg_rr_ms
                          FROM athletes ORDER BY last_name, first_name"""):
    print(f"{row[0]:15} {row[1]:10} | RMSSD={row[2] or 0:3} | RR={row[3] or 0:4} мс")

print("\n=== Статистика по записям ===")
cnt      = cur.execute("SELECT COUNT(*) FROM ecg_records").fetchone()[0]
with_raw = cur.execute("SELECT COUNT(*) FROM ecg_records WHERE raw_data IS NOT NULL").fetchone()[0]
avg_raw  = cur.execute("""SELECT COALESCE(AVG(LENGTH(raw_data)),0)
                          FROM (SELECT raw_data FROM ecg_records
                                WHERE raw_data IS NOT NULL LIMIT 50)""").fetchone()[0]
avg_dur  = cur.execute("SELECT COALESCE(AVG(duration_seconds),0) FROM ecg_records").fetchone()[0]
avg_sdnn = cur.execute("SELECT COALESCE(AVG(sdnn),0) FROM ecg_records").fetchone()[0]
avg_si   = cur.execute("SELECT COALESCE(AVG(stress_si),0) FROM ecg_records").fetchone()[0]

print(f"Всего записей:        {cnt}")
print(f"С raw_data:           {with_raw} (~{with_raw * avg_raw / 1048576:.0f} MB)")
print(f"Средняя длительность: {avg_dur:.0f} сек")
print(f"Средний SDNN:         {avg_sdnn:.1f} мс")
print(f"Средний ИС:           {avg_si:.1f}")

print("\n=== Индексы ===")
for (name,) in cur.execute("SELECT name FROM sqlite_master WHERE type='index'"):
    print(" ", name)

conn.close()