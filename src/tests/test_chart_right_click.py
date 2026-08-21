"""
Интеграционный тест: ПКМ по графику вызывает on_reset, и график сбрасывает масштаб на 10 лет.

Проверяет полный цикл:
1. Виджет уведомляет оркестратор (on_reset).
2. Оркестратор очищает view и вызывает перерисовку.
3. График физически меняет масштаб оси X на полный диапазон данных.
"""
import datetime
import os
import sys
import tkinter as tk

PROJECT_DIR = r"C:\s21\projects\analysis_HVR\src"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from metricplot import MetricPlot, MetricSpec
from matplotlib.backend_bases import MouseEvent


def test_right_click_resets_to_10_year_range():
    """
    Сценарий:
    1. График загружает данные за 10 лет (прямая инъекция, без моков БД).
    2. График искусственно сужен до 10 дней.
    3. Симулируем ПКМ.
    4. Проверяем, что on_reset вызван И масштаб стал ~3650 дней.
    """
    root = tk.Tk()
    root.withdraw()  # Скрываем окно

    try:
        spec = MetricSpec("test", "Тест", "ед.", lambda r: 50)
        plot = MetricPlot(root, spec, db_path=":memory:")
        plot.pack(fill="both", expand=True)

        # 1. ПРЯМАЯ ИНЪЕКЦИЯ ДАННЫХ (гарантируем 10 лет данных, минуя SQLAlchemy)
        today = datetime.date.today()
        date_10_years_ago = today - datetime.timedelta(days=3650)
        
        plot._values = [
            (datetime.datetime.combine(date_10_years_ago, datetime.time(12, 0)), 50),
            (datetime.datetime.combine(today, datetime.time(12, 0)), 50)
        ]
        plot._start = date_10_years_ago
        plot._end = today
        plot._loading = False

        # 2. ИСКУССТВЕННО СУЖАЕМ МАСШТАБ до 10 дней (чтобы было что "расширять")
        today_ord = today.toordinal()
        plot.view = (today_ord - 10, today_ord + 1)
        plot._draw()
        root.update()

        initial_xlim = plot.ax.get_xlim()
        initial_span = initial_xlim[1] - initial_xlim[0]
        assert initial_span < 20, f"Ожидался узкий зум (<20 дней), получено {initial_span}"

        # 3. ИМИТАЦИЯ ДЕЙСТВИЙ ОРКЕСТРАТОРА ПРИ ПКМ
        reset_calls = []
        
        def mock_orchestrator_reset():
            reset_calls.append(True)
            # Оркестратор сбрасывает пользовательский зум и таймфрейм
            plot.view = None
            plot._current_tf = None
            # И заставляет график перерисоваться по полному диапазону (_start ... _end)
            plot._draw()

        plot.on_reset = mock_orchestrator_reset

        # Симулируем ПКМ (button=3) через API matplotlib
        event = MouseEvent('button_press_event', plot.canvas, x=100, y=100, button=3)
        plot.canvas.callbacks.process('button_press_event', event)
        root.update()

        # 4. ПРОВЕРКА 1: Контракт (вызван ли колбэк)
        assert reset_calls, "ПКМ должен вызвать on_reset"
        assert len(reset_calls) == 1, f"on_reset должен вызываться 1 раз, получено {len(reset_calls)}"

        # 5. ПРОВЕРКА 2: Реальный результат (масштаб графика)
        final_xlim = plot.ax.get_xlim()
        final_span = final_xlim[1] - final_xlim[0]

        # 10 лет = 3650 дней. Допускаем погрешность ±10 дней из-за високосных годов 
        # и внутренней логики добавления +1 к _end в _view_ordinals
        assert 3640 < final_span < 3660, \
            f"Ожидался масштаб ~10 лет (3650 дней), но получен размах {final_span:.1f} дней"

        print(f"Тест пройден! ПКМ вызвал on_reset, масштаб изменен с {initial_span:.1f} до {final_span:.1f} дней.")

    finally:
        root.destroy()


if __name__ == "__main__":
    print("\n=== Запуск интеграционного теста ПКМ ===\n")
    test_right_click_resets_to_10_year_range()
    print("\nВсе проверки пройдены успешно!")