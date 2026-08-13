"""
Единый менеджер пути к базе данных проекта анализа ВРС.

После перехода на SQLAlchemy ORM в этом файле осталось только:
- определение пути к файлу БД (get_db_path)
- константы путей

Всё остальное (схема, подключения, индексы) теперь в models.py.
"""
import os
import sys
from typing import Optional

# ============================================================
# КОНФИГУРАЦИЯ ПУТЕЙ
# ============================================================
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_RELATIVE = "../data/ecg.db"


# ============================================================
# ПУТЬ К БАЗЕ ДАННЫХ
# ============================================================
def get_db_path(relative_path: Optional[str] = None) -> str:
    """
    Возвращает абсолютный путь к файлу БД.

    В режиме exe (--onedir): база лежит рядом с exe в папке data/.
    В обычном режиме (python app.py): ../data/ecg.db относительно scripts/.
    """
    # === РЕЖИМ EXE ===
    if getattr(sys, "frozen", False) and relative_path is None:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.normpath(os.path.join(exe_dir, "data", "ecg.db"))

    # === ОБЫЧНЫЙ РЕЖИМ ===
    if relative_path is None:
        relative_path = DEFAULT_DB_RELATIVE

    if os.path.isabs(relative_path):
        return os.path.normpath(relative_path)

    return os.path.normpath(os.path.join(SCRIPTS_DIR, relative_path))