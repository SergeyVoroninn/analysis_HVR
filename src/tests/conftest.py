"""
conftest.py — общие фикстуры для всех тестов проекта.
Создает единственный экземпляр Tk-окна на весь запуск pytest (scope="session").
"""
import tkinter as tk
import pytest


@pytest.fixture(scope="session")
def gui_root():
    """
    Единственный экземпляр tk.Tk() на всю сессию тестирования.
    Используется всеми GUI-тестами для избежания конфликтов инициализации Tcl/Tk.
    """
    root = tk.Tk()
    root.withdraw()  # Скрываем окно, чтобы не мешало
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass  # Игнорируем ошибки, если окно уже уничтожено