"""
Тест ПКМ по yearmap: проверка установки масштаба, курсора yearmap и weekmap,
и сохранение этого состояния при смене атлетов.
"""
import datetime
import os
import sys
import tkinter as tk
from unittest.mock import MagicMock, Mock

PROJECT_DIR = r"C:\s21\projects\analysis_HVR\src"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from yearmap import YearHeatmap, X0, Y0
from weekmap import WeekHeatmap
from charts import ChartsPanel, TP_METRIC
from orchestrator import AppOrchestrator
from heatmap import Heatmap  # Импортируем составной виджет для проверки синхронизации


def test_yearmap_right_click_sync_and_persistence():
    """
    Сценарий:
    1. Инициализируем Heatmap (yearmap + weekmap) и Charts.
    2. Делаем ПКМ по yearmap на 20-й неделе.
    3. Проверяем, что обновились: yearmap.week, weekmap.week_start и charts.zoom.
    4. Переключаемся на другого атлета.
    5. Проверяем, что ВСЕ три состояния (yearmap, weekmap, charts) НЕ "уплыли".
    """
    root = tk.Tk()
    root.withdraw()

    try:
        # 1. Создаем составной виджет Heatmap (он сам свяжет yearmap и weekmap)
        heatmap = Heatmap(root, db_path=":memory:")
        heatmap.pack()
        
        charts = ChartsPanel(root, metrics=[TP_METRIC], db_path=":memory:")
        charts.pack()
        
        mock_settings = MagicMock()
        orchestrator = AppOrchestrator(heatmap=heatmap, charts=charts, settings=mock_settings)

        # 2. Имитируем данные Атлета А (2024 год)
        heatmap.year = 2024
        heatmap.year_map._recalc_year()
        
        # Эмулируем загрузку данных в графики
        for p in charts._plots:
            p._athlete = "athlete_A"
            p._start = datetime.date(2024, 1, 1)
            p._end = datetime.date(2024, 12, 31)
            p._values = [(datetime.datetime(2024, 6, 1), 50)]
            p._loading = False
            p._draw()
        root.update()

        # 3. Симулируем ПКМ по yearmap на 20-й неделе
        click_w = 20
        event = Mock()
        event.x = X0 + click_w * heatmap.year_map._step + heatmap.year_map._cell // 2
        event.y = Y0 + 3 * heatmap.year_map._step
        
        heatmap.year_map._on_right_click(event)
        root.update()

        # Ожидаемая дата понедельника 20-й недели 2024 года
        expected_monday = heatmap.year_map.week_start_date(click_w)

        # --- ПРОВЕРКИ ПОСЛЕ ПКМ ---
        # A. Курсор yearmap
        assert heatmap.year_map.week == click_w, \
            f"yearmap.week должен быть {click_w}, получено {heatmap.year_map.week}"
        
        # B. Синхронизация weekmap (ЭТО БЫЛО СЛАБЫМ МЕСТОМ)
        assert heatmap.week_map.week_start == expected_monday, \
            f"weekmap.week_start должен обновиться до {expected_monday}, получено {heatmap.week_map.week_start}"
        
        # C. Масштаб графиков (весь год ~365 дней)
        zoom = charts.zoom
        assert zoom is not None, "Масштаб графиков не должен быть None после ПКМ"
        span = zoom[1] - zoom[0]
        assert 360 < span < 370, f"Масштаб должен быть ~365 дней, получено {span}"

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
        # A. Курсор yearmap не уплыл
        assert heatmap.year_map.week == click_w, \
            f"yearmap.week должен остаться {click_w}, получено {heatmap.year_map.week}"
        
        # B. weekmap не уплыл
        assert heatmap.week_map.week_start == expected_monday, \
            f"weekmap.week_start должен остаться {expected_monday}, получено {heatmap.week_map.week_start}"
        
        # C. Масштаб графиков не уплыл
        zoom_after = charts.zoom
        assert zoom_after is not None, "Масштаб сбросился в None при смене атлета"
        span_after = zoom_after[1] - zoom_after[0]
        assert 360 < span_after < 370, f"Масштаб должен остаться ~365 дней, получено {span_after}"

        print("✅ Тест пройден: ПКМ синхронизирует yearmap, weekmap и charts, и состояние сохраняется")

    finally:
        root.destroy()


if __name__ == "__main__":
    print("\n" + "="*80)
    print("ТЕСТ: ПКМ по yearmap, синхронизация weekmap и сохранение при смене атлетов")
    print("="*80)
    test_yearmap_right_click_sync_and_persistence()
    print("\n" + "="*80)
    print("ТЕСТ ЗАВЕРШЁН УСПЕШНО!")
    print("="*80 + "\n")