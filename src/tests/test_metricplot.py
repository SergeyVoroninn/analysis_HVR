"""
Тесты событий MetricPlot: клик, двойной клик (игнорируется), ПКМ, панорамирование.
Проверяет реальное, актуальное поведение виджета.
"""
import datetime
import os
import sys
import time as _time
import pytest
from unittest.mock import Mock, MagicMock

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)

from metricplot import MetricPlot, MetricSpec


@pytest.fixture
def plot():
    """Создает частично замоканный экземпляр MetricPlot для тестирования логики событий."""
    spec = MetricSpec("test", "Test", "unit", lambda r: r.value)
    
    # Используем __new__, чтобы избежать вызова __init__ и создания реальных Tk-виджетов
    p = MetricPlot.__new__(MetricPlot)
    p.spec = spec
    p.db_path = ""
    p._athlete = "test_athlete"
    p._start = datetime.date(2026, 1, 1)
    p._end = datetime.date(2026, 12, 31)
    p._values = [(datetime.datetime(2026, 6, 15, 10), 100)]
    p.view = None
    p._pan = None
    p._single_timer = None
    p._click_t = 0.0
    p._click_x = 0.0
    p._click_y = 0.0
    p._current_tf = None
    p._forced_tf = None
    p.on_view_changed = None
    p.on_year_pick = None
    p.on_reset = Mock()
    p.on_single_click = Mock()
    
    # Мокаем методы Tkinter и Matplotlib
    p.after = Mock(return_value="timer_ok")
    p.after_cancel = Mock()
    p.ax = Mock()
    p.ax.get_window_extent = Mock(return_value=Mock(width=1000))
    p.canvas = Mock()
    p.widget = Mock()
    
    # Мокаем внутренние методы для изоляции теста
    p._ord = Mock(side_effect=lambda x: x.toordinal() if hasattr(x, 'toordinal') else float(x))
    p._view_ordinals = Mock(return_value=(100.0, 200.0))
    p._commit_view = Mock()
    p._draw = Mock()
    
    return p


def _event(button=1, xdata=None, x=100, y=100):
    """Хелпер для создания фейкового события мыши."""
    e = Mock()
    e.button = button
    e.xdata = xdata
    e.x = x
    e.y = y
    return e


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_schedules_callback(plot):
    """Одинарный клик планирует вызов on_single_click через 500 мс."""
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    plot.after.assert_called_once()
    args, kwargs = plot.after.call_args
    assert args[0] == 500  # Задержка 500 мс

def test_single_click_sets_pan_state(plot):
    """Одинарный клик инициализирует состояние панорамирования."""
    plot._on_press(_event(button=1, xdata=738000, x=150, y=100))
    assert plot._pan is not None
    assert plot._pan[0] == 150  # Начальная координата X

def test_single_click_does_not_commit_view_immediately(plot):
    """Одинарный клик НЕ должен сразу менять масштаб (ждет таймер или движение)."""
    plot._on_press(_event(button=1, xdata=738000))
    plot._commit_view.assert_not_called()

def test_single_click_fires_after_delay(plot):
    """По истечении таймера вызывается on_single_click."""
    plot._on_press(_event(button=1, xdata=738000))
    d = datetime.date.fromordinal(int(738000))
    plot._fire_single(d)
    plot.on_single_click.assert_called_once_with(d)


# ======================== ДВОЙНОЙ КЛИК (ЯВНО ИГНОРИРУЕТСЯ) ========================

def test_double_click_is_explicitly_ignored(plot):
    """
    Двойной клик по графику игнорируется (не вызывает ни зума, ни одинарного клика).
    Это сделано намеренно для эргономики (зум делается колесом или через heatmap).
    """
    # Имитируем первый клик
    plot._click_t = _time.monotonic() - 0.1
    plot._click_x = 100
    plot._click_y = 100
    plot.after.reset_mock()
    plot._commit_view.reset_mock()
    plot.on_single_click.reset_mock()

    # Имитируем второй клик (двойной)
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))

    # Проверяем, что НИЧЕГО не произошло
    plot._commit_view.assert_not_called()
    plot.on_single_click.assert_not_called()
    plot.after.assert_not_called()  # Таймер одинарного клика не должен быть установлен

def test_click_different_position_is_not_double(plot):
    """Если координаты второго клика отличаются > 6px, это считается новым одинарным кликом."""
    plot._click_t = _time.monotonic() - 0.1
    plot._click_x = 100
    plot._click_y = 100
    plot.after.reset_mock()
    
    # Клик далеко от первого
    plot._on_press(_event(button=1, xdata=738000, x=200, y=200))
    
    # Должен сработать как новый одинарный клик
    plot.after.assert_called()

def test_click_too_slow_is_not_double(plot):
    """Если между кликами прошло > 0.45 сек, это считается новым одинарным кликом."""
    plot._click_t = _time.monotonic() - 1.0
    plot._click_x = 100
    plot._click_y = 100
    plot.after.reset_mock()
    
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    
    # Должен сработать как новый одинарный клик
    plot.after.assert_called()


# ======================== ПРАВЫЙ КЛИК (ПКМ) ========================

def test_right_click_calls_reset(plot):
    """ПКМ должен вызвать колбэк on_reset."""
    plot._on_press(_event(button=3, xdata=738000))
    plot.on_reset.assert_called_once()

def test_right_click_clears_current_tf(plot):
    """ПКМ должен сбросить текущий таймфрейм."""
    plot._current_tf = "SOME_TF"
    plot._on_press(_event(button=3, xdata=738000))
    assert plot._current_tf is None

def test_right_click_does_not_commit_view(plot):
    """ПКМ не должен напрямую менять view через _commit_view (это делает оркестратор)."""
    plot._on_press(_event(button=3, xdata=738000))
    plot._commit_view.assert_not_called()


# ======================== ГРАНИЧНЫЕ СЛУЧАИ КЛИКА ========================

def test_click_no_xdata_ignored(plot):
    """Клик вне области данных (xdata=None) игнорируется."""
    plot._on_press(_event(button=1, xdata=None))
    plot.on_single_click.assert_not_called()
    plot._commit_view.assert_not_called()

def test_click_no_start_ignored(plot):
    """Клик при отсутствии данных (_start=None) игнорируется."""
    plot._start = None
    plot._on_press(_event(button=1, xdata=738000))
    plot.on_single_click.assert_not_called()
    plot._commit_view.assert_not_called()

def test_click_button_2_ignored(plot):
    """Средняя кнопка мыши (button=2) игнорируется."""
    plot._on_press(_event(button=2, xdata=738000))
    plot.on_single_click.assert_not_called()
    plot.on_reset.assert_not_called()

def test_click_cancels_previous_timer(plot):
    """Новый клик отменяет предыдущий таймер одинарного клика."""
    plot._single_timer = "prev_timer"
    plot._on_press(_event(button=1, xdata=738000))
    plot.after_cancel.assert_called_once_with("prev_timer")


# ======================== ПАНОРАМИРОВАНИЕ ========================

def test_motion_pans_view(plot):
    """Движение мыши с зажатой ЛКМ должно вызывать _commit_view со сдвигом."""
    plot._on_press(_event(button=1, xdata=738000, x=150, y=100))
    assert plot._pan is not None

    # Имитируем движение мыши вправо на 50 пикселей
    event = _event(button=1, x=200)
    plot._on_motion(event)
    
    plot._commit_view.assert_called()
    lo, hi = plot._commit_view.call_args[0]
    assert lo < hi  # Диапазон должен быть валидным

def test_motion_without_pan_ignored(plot):
    """Движение мыши без предварительно зажатой ЛКМ игнорируется."""
    plot._pan = None
    plot._on_motion(_event(button=1, x=200))
    plot._commit_view.assert_not_called()

def test_motion_wrong_button_ignored(plot):
    """Движение мыши с зажатой не-ЛКМ (например, ПКМ) игнорируется."""
    plot._pan = (100, 100.0, 200.0)
    plot._on_motion(_event(button=3, x=200))
    plot._commit_view.assert_not_called()

def test_release_clears_pan(plot):
    """Отпускание кнопки мыши сбрасывает состояние панорамирования."""
    plot._pan = (100, 100.0, 200.0)
    plot._on_release(_event())
    assert plot._pan is None

def test_motion_cancels_single_click_timer(plot):
    """Панорамирование (движение мыши) должно немедленно отменять таймер одинарного клика."""
    # 1. Имитируем нажатие (таймер установлен)
    plot._on_press(_event(button=1, xdata=738000, x=150, y=100))
    assert plot._single_timer is not None, "Таймер должен быть установлен при нажатии"
    
    # Сохраняем ID таймера для проверки
    timer_id = plot._single_timer

    # 2. Имитируем движение мыши (начало панорамирования)
    plot._on_motion(_event(button=1, x=200))
    
    # 3. Проверяем, что таймер был отменен и переменная обнулена
    plot.after_cancel.assert_called_once_with(timer_id)
    assert plot._single_timer is None, "Таймер должен быть обнулен после начала движения"