"""
Тест сохранения масштаба при смене атлета после ПКМ.
Проверяет все комбинации переходов между 3 атлетами с разными диапазонами.
"""
import datetime
import os
import sys
import tkinter as tk
from unittest.mock import MagicMock

PROJECT_DIR = r"C:\s21\projects\analysis_HVR\src"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from charts import ChartsPanel, TP_METRIC
from orchestrator import AppOrchestrator


def _inject_and_draw(charts, athlete_id, days_ago_start, days_ago_end):
    """Инжекция данных и принудительная отрисовка."""
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days_ago_start)
    end_date = today - datetime.timedelta(days=days_ago_end)
    
    for p in charts._plots:
        p._athlete = athlete_id
        p._start = start_date
        p._end = end_date
        p._values = [
            (datetime.datetime.combine(start_date, datetime.time(12, 0)), 50),
            (datetime.datetime.combine(end_date, datetime.time(12, 0)), 50)
        ]
        p._loading = False
        p._draw()


def _get_view_span(charts):
    """Возвращает реальный диапазон графика в днях."""
    if not charts._plots:
        return None
    p0 = charts._plots[0]
    v = p0._view_ordinals()
    if v is None:
        return None
    return v[1] - v[0]


def test_pcm_persistence_across_three_athletes():
    """
    Сценарий:
    1. Атлет A: 10 лет данных (большой диапазон)
    2. Атлет B: 1 год данных (средний диапазон)
    3. Атлет C: 1 месяц данных (малый диапазон)
    
    Для каждого атлета:
    - Делаем ПКМ (устанавливаем полный диапазон этого атлета)
    - Переключаемся на других атлетов
    - Проверяем, что масштаб сохраняется (не сбивается на полный диапазон нового атлета)
    """
    root = tk.Tk()
    root.withdraw()

    try:
        charts = ChartsPanel(root, metrics=[TP_METRIC], db_path=":memory:")
        charts.pack(fill="both", expand=True)
        
        mock_settings = MagicMock()
        orchestrator = AppOrchestrator(heatmap=MagicMock(), charts=charts, settings=mock_settings)

        athletes = {
            "A_10years": 3650,
            "B_1year": 365,
            "C_1month": 30
        }

        print("\n" + "="*80)
        print("ТЕСТ: Сохранение масштаба после ПКМ при смене атлета")
        print("="*80)

        # Тестируем каждый атлет как исходный
        for source_athlete, source_days in athletes.items():
            print(f"\n{'='*80}")
            print(f"ИСХОДНЫЙ АТЛЕТ: {source_athlete} ({source_days} дней)")
            print('='*80)

            # 1. Загружаем исходного атлета
            _inject_and_draw(charts, source_athlete, source_days, 0)
            root.update()

            # 2. Делаем ПКМ (сохраняем полный диапазон)
            p0 = charts._plots[0]
            pcm_range = (p0._ord(p0._start), p0._ord(p0._end) + 1)
            orchestrator._saved_range = pcm_range
            print(f"  ПКМ установлен: {pcm_range[1] - pcm_range[0]:.0f} дней")

            # 3. Переключаемся на каждого другого атлета
            for target_athlete, target_days in athletes.items():
                if target_athlete == source_athlete:
                    continue

                print(f"\n  → Переход на {target_athlete} ({target_days} дней)")
                
                # Сохраняем ожидаемый диапазон (должен остаться как у исходного)
                expected_span = pcm_range[1] - pcm_range[0]

                # Переключаем атлета
                orchestrator.sync_athlete(target_athlete)
                _inject_and_draw(charts, target_athlete, target_days, 0)
                root.update()

                # Проверяем результат
                actual_span = _get_view_span(charts)
                print(f"    Ожидалось: {expected_span:.0f} дней")
                print(f"    Получено:  {actual_span:.0f} дней")

                # Проверяем, что масштаб сохранился
                assert actual_span is not None, "Диапазон стал None!"
                
                # Допускаем небольшую погрешность (±1 день)
                assert abs(actual_span - expected_span) <= 1.0, \
                    f"Масштаб сбился! Ожидалось {expected_span:.0f} дней, получено {actual_span:.0f} дней"
                
                print(f"    ✓ Масштаб сохранён корректно")

        print("\n" + "="*80)
        print("✅ ВСЕ ПЕРЕХОДЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("="*80)

    finally:
        root.destroy()


if __name__ == "__main__":
    success = test_pcm_persistence_across_three_athletes()
    if not success:
        exit(1)