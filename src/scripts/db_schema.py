"""Выводит полную структуру базы данных (таблицы, колонки, индексы, FK)."""
import os
import sys
import sqlite3

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from database import get_db_path

db_path = get_db_path()
size_mb = os.path.getsize(db_path) / 1024 / 1024

print(f"📁 База: {db_path}")
print(f"💾 Размер: {size_mb:.2f} MB\n")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# === Список таблиц ===
tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
)]
print(f"=== Таблиц: {len(tables)} ===\n")

for table in tables:
    # Количество записей
    count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    
    # Колонки: (cid, name, type, notnull, dflt_value, pk)
    cols = cur.execute(f"PRAGMA table_info({table})").fetchall()
    
    # Индексы
    indexes = cur.execute(f"PRAGMA index_list({table})").fetchall()
    
    # Foreign keys (8 колонок: id, seq, table, from, to, on_update, on_delete, match)
    fks = cur.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    
    print(f"┌─ {table} ({count} записей)")
    print(f"│")
    
    # Колонки
    print(f"│  Колонки:")
    for cid, name, dtype, notnull, default, pk in cols:
        flags = []
        if pk:
            flags.append("PK")
        if notnull:
            flags.append("NOT NULL")
        if default is not None:
            flags.append(f"DEFAULT {default}")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"│    {name:25} {dtype:15}{flag_str}")
    
    # Foreign keys
    if fks:
        print(f"│")
        print(f"│  Foreign Keys:")
        for fk_id, seq, ref_table, from_col, to_col, on_update, on_delete, match in fks:
            print(f"│    {from_col} → {ref_table}.{to_col}  ON DELETE {on_delete}")
    
    # Индексы
    if indexes:
        print(f"│")
        print(f"│  Индексы:")
        for seq, idx_name, unique, origin, partial in indexes:
            idx_cols = cur.execute(f"PRAGMA index_info({idx_name})").fetchall()
            col_names = [c[2] for c in idx_cols]
            uniq = "UNIQUE " if unique else ""
            print(f"│    {uniq}{idx_name:40} ({', '.join(col_names)})")
    
    print(f"└{'─' * 70}\n")

# === Связи между таблицами ===
print("=" * 70)
print("=== Связи (ER-диаграмма) ===\n")
for table in tables:
    fks = cur.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    for fk_id, seq, ref_table, from_col, to_col, on_update, on_delete, match in fks:
        print(f"  {table}.{from_col}  ──→  {ref_table}.{to_col}")

conn.close()