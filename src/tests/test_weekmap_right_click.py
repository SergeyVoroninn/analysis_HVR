"""
Тест ПКМ по weekmap: проверка установки масштаба на неделю (7 дней),
синхронизации курсора yearmap и сохранения состояния при смене атлетов.
"""
import datetime
import os
import sys
import pytest
from unittest.mock import MagicMock, Mock

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from charts import ChartsPanel, TP_METRIC
from orchestrator import AppOrchestrator
from heatmap import Heatmap


# Используем общую фикстуру gui_root из conftest.py
def test_weekmap_right_click_sync_and_persistence(gui_root):
    """
    Сценарий:
    1. Инициализируем Heatmap (yearmap + weekmap) и Charts.
    2. Устанавливаем weekmap на конкретную неделю (15-я неделя 2024 года).
    3. Делаем ПКМ по weekmap → zoom на неделю (7 дней) + курсор yearmap.
    4. Проверяем синхронизацию.
    5. Переключаемся на другого атлета.
    6. Проверяем, что ВСЕ состояния НЕ "уплыли".
    """
    root = gui_root

    # 1. Создаем составной виджет Heatmap и Charts
    heatmap = Heatmap(root, db_path=":memory:")
    heatmap.pack()
    
    charts = ChartsPanel(root, metrics=[TP_METRIC], db_path=":memory:")
    charts.pack()
    
    mock_settings = MagicMock()
    orchestrator = AppOrchestrator(heatmap=heatmap, charts=charts, settings=mock_settings)

    # 2. Имитируем данные Атлета А (2024 год)
    heatmap.year = 2024
    heatmap.year_map._recalc_year()
    
    # Устанавливаем weekmap на 15-ю неделю 2024 года (понедельник = 8 апреля 2024)
    week_15_monday = datetime.date(2024, 4, 8)
    heatmap.week_map.week_start = week_15_monday
    
    # Эмулируем загрузку данных в графики (прямая инъекция для стабильности)
    for p in charts._plots:
        p._athlete = "athlete_A"
        p._start = datetime.date(2024, 1, 1)
        p._end = datetime.date(2024, 12, 31)
        p._values = [(datetime.datetime(2024, 6, 1), 50)]
        p._loading = False
        p._draw()
    root.update()

    # 3. Симулируем ПКМ по weekmap
    event = Mock()
    event.x = 50
    event.y = 50
    
    heatmap.week_map._on_week_rmb_click(event)
    root.update()

    # Ожидаемые значения
    expected_week_start = week_15_monday
    expected_zoom_span = 7.0  # неделя = ровно 7 дней

    # --- ПРОВЕРКИ ПОСЛЕ ПКМ ---
    # A. Масштаб графиков установлен на неделю (7 дней)
    zoom = charts.zoom
    assert zoom is not None, "Масштаб графиков не должен быть None после ПКМ"
    span = zoom[1] - zoom[0]
    assert abs(span - expected_zoom_span) < 0.1, \
        f"Масштаб должен быть {expected_zoom_span} дней (неделя), получено {span}"
    
    # B. Курсор yearmap синхронизирован с weekmap
    year_start = heatmap.year_map._year_start
    expected_yearmap_week = (week_15_monday - year_start).days // 7
    
    assert heatmap.year_map.week == expected_yearmap_week, \
        f"yearmap.week должен быть {expected_yearmap_week}, получено {heatmap.year_map.week}"
    
    # C. week_start в weekmap не изменился
    assert heatmap.week_map.week_start == expected_week_start, \
        f"weekmap.week_start должен остаться {expected_week_start}, получено {heatmap.week_map.week_start}"

    # Сохраняем состояние, как это делает оркестратор
    orchestrator._saved_range = zoom

    # 4. Переключаемся на Атлета Б (тоже 2024 год)
    for p in charts._plots:
        p._athlete = "athlete_B"
        p._start = datetime.date(2024, 1, 1)
        p._end = datetime.date(2024, 12, 31)
        p._values = [(datetime.datetime(2024, 8, 1), 60)]
        p._loading = False
        p._draw()
    
    orchestrator.sync_athlete("athlete_B")
    root.update()

    # --- ПРОВЕРКИ ПОСЛЕ СМЕНЫ АТЛЕТА ---
    # A. Масштаб графиков не уплыл (остался 7 дней)
    zoom_after = charts.zoom
    assert zoom_after is not None, "Масштаб сбросился в None при смене атлета"
    span_after = zoom_after[1] - zoom_after[0]
    assert abs(span_after - expected_zoom_span) < 0.1, \
        f"Масштаб должен остаться {expected_zoom_span} дней, получено {span_after}"
    
    # B. Курсор yearmap не уплыл
    assert heatmap.year_map.week == expected_yearmap_week, \
        f"yearmap.week должен остаться {expected_yearmap_week}, получено {heatmap.year_map.week}"
    
    # C. weekmap не уплыл
    assert heatmap.week_map.week_start == expected_week_start, \
        f"weekmap.week_start должен остаться {expected_week_start}, получено {heatmap.week_map.week_start}"

    print("✅ Тест пройден: ПКМ по weekmap синхронизирует zoom и yearmap, и состояние сохраняется")