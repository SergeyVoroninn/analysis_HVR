"""
Тест, который ПРЯМО проверяет код из app.py.
Если вы закомментируете save_state в app.py, этот тест УПАДЕТ.
"""
import os
import sys
import json
import tempfile
import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from appsettings import AppSettings
from charts import ChartsPanel, TP_METRIC
from heatmap import Heatmap
from orchestrator import AppOrchestrator

# ИМПОРТИРУЕМ РЕАЛЬНУЮ ФУНКЦИЮ ИЗ app.py!
from app import handle_app_close


@pytest.fixture
def temp_settings_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_real_app_py_close_saves_state(temp_settings_file):
    """
    Проверяет, что РЕАЛЬНАЯ функция handle_app_close из app.py 
    действительно сохраняет состояние на диск.
    """
    # 1. Начальное состояние (старые данные)
    settings = AppSettings(path=temp_settings_file)
    settings.set("athlete_id", "OLD_ATHLETE")
    settings.set("year", 2020)
    settings.save()

    # 2. Имитация запущенного приложения
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    
    hm = Heatmap(root, db_path=":memory:")
    charts = ChartsPanel(root, metrics=[TP_METRIC], db_path=":memory:")
    orchestrator = AppOrchestrator(hm, charts, settings)

    # 3. Создаем "фейковую" панель атлетов, которая возвращает нового атлета
    class MockPanel:
        def selected(self):
            return ("NEW_ATHLETE_FROM_APP", "Иван Иванов")

    mock_panel = MockPanel()

    # Пользователь поработал и изменил данные в оркестраторе
    orchestrator.sync_athlete("NEW_ATHLETE_FROM_APP")
    hm.year = 2024
    charts.zoom = [738000, 738010]

    # 4. ВЫЗЫВАЕМ РЕАЛЬНУЮ ФУНКЦИЮ ЗАКРЫТИЯ ИЗ app.py
    # Именно она должна вызвать save_state
    handle_app_close(mock_panel, orchestrator, root)

    # 5. ЖЕСТКАЯ ПРОВЕРКА ДИСКА
    # Если в app.py закомментирован orchestrator.save_state(), 
    # файл на диске НЕ обновится, и тест УПАДЕТ здесь:
    with open(temp_settings_file, 'r', encoding='utf-8') as f:
        disk_data = json.load(f)

    assert disk_data.get("athlete_id") == "NEW_ATHLETE_FROM_APP", (
        "КРИТИЧЕСКИЙ БАГ В app.py: handle_app_close не сохранил атлета! "
        "Проверьте, не закомментирована ли строка orchestrator.save_state() в функции handle_app_close."
    )
    assert disk_data.get("year") == 2024, "Год не был сохранен функцией из app.py!"
    assert disk_data.get("zoom") == [738000, 738010], "Зум не был сохранен функцией из app.py!"