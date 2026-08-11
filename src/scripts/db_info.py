"""Быстрая информация о базе данных."""
from database import get_db_path
import sqlite3

db_path = get_db_path()
print(f"База: {db_path}\n")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("=== Спортсмены ===")
for row in cur.execute("SELECT last_name, first_name, hrv_rmssd_baseline, avg_rr_ms FROM athletes"):
    print(f"{row[0]:15} {row[1]:10} | RMSSD={row[2]:3} | RR={row[3]:4} мс")

print(f"\n=== Статистика по записям ===")
stats = cur.execute("""
    SELECT AVG(sdnn), AVG(stress_si), COUNT(*) 
    FROM ecg_records
""").fetchone()
print(f"Средний SDNN:  {stats[0]:.1f} мс")
print(f"Средний ИС:    {stats[1]:.1f}")
print(f"Всего записей: {stats[2]}")

conn.close()