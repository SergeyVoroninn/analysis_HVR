"""
Единый менеджер пути к базе данных проекта анализа ВРС.
Теперь находится в корневой директории src/.
"""
import os
import sys
from typing import Optional

# Базовая директория теперь src/ (родительская для этого файла)
SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def get_db_path(relative_path: Optional[str] = None, db_name: str = "ecg.db") -> str:
    """
    Возвращает абсолютный путь к файлу БД.

    Args:
        relative_path: Относительный путь (если задан, db_name игнорируется).
        db_name: Имя файла базы данных (по умолчанию "ecg.db").
    """
    # === РЕЖИМ EXE (PyInstaller) ===
    if getattr(sys, "frozen", False) and relative_path is None:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.normpath(os.path.join(exe_dir, "data", db_name))

    # === ОБЫЧНЫЙ РЕЖИМ (python app.py или тесты) ===
    if relative_path is None:
        # По умолчанию ищем ../data/ecg.db относительно директории src/
        relative_path = f"../data/{db_name}"

    if os.path.isabs(relative_path):
        return os.path.normpath(relative_path)

    return os.path.normpath(os.path.join(SRC_DIR, relative_path))