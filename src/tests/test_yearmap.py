"""
Тесты кликов по yearmap: одинарный, двойной, ПКМ, заполненные/пустые недели.
Проверяет реальное поведение и синхронизацию с оркестратором.
"""
import datetime
import os
import sys
import time as _time
import pytest
from unittest.mock import Mock

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from yearmap import YearHeatmap, X0, Y0


@pytest.fixture
def yearmap():
    wm = YearHeatmap.__new__(YearHeatmap)
    wm._cell = 14
    wm._step = 15
    wm._year = 2026
    wm._week = None
    wm._year_start = datetime.date(2026, 1, 1) - datetime.timedelta(days=datetime.date(2026, 1, 1).weekday())
    wm.db_path = ""
    
    # Колбэки
    wm.on_week_pick = Mock()
    wm.on_week_dbl = Mock()
    wm.on_year_zoom = Mock()
    wm.on_month_zoom = Mock()
    wm.on_year_change = Mock()
    
    wm._date_map = {
        "2026-08-17": {"count": 1, "worst": None},
        "2026-08-19": {"count": 3, "worst": None},
        "2026-08-21": {"count": 1, "worst": "crit"},
        "2026-07-01": {"count": 2, "worst": None},
    }
    wm._cells = [Mock() for _ in range(53 * 7)]
    wm._colors = [None] * (53 * 7)
    wm._month_labels = [Mock() for _ in range(12)]
    
    # Состояние кликов
    wm._click_t = 0.0
    wm._click_w = -1
    wm._single_timer = None
    
    # Методы Tkinter
    wm.after = Mock(return_value="timer_123")
    wm.after_cancel = Mock()
    wm.coords = Mock()
    wm.delete = Mock()
    wm.itemconfigure = Mock()
    wm.create_rectangle = Mock()
    wm.create_text = Mock()
    wm.config = Mock()
    return wm


def _fire_single_now(yearmap, monday):
    """Прямой вызов для проверки payload колбэка."""
    yearmap._fire_week_pick(monday)


def _simulate_click(yearmap, w, time_offset=0.0):
    """Симулирует событие клика в _on_click."""
    x = X0 + w * yearmap._step + yearmap._cell // 2
    y = Y0 + 3 * yearmap._step + yearmap._cell // 2
    event = Mock()
    event.x = x
    event.y = y
    
    yearmap._click_t = _time.monotonic() - time_offset
    yearmap._click_w = w
    # Не сбрасываем _single_timer, чтобы тесты могли управлять им
    
    yearmap._on_click(event)


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_schedules_timer(yearmap):
    """Одинарный клик планирует вызов on_week_pick через 300 мс."""
    _simulate_click(yearmap, w=33, time_offset=1.0) # 1 сек назад = новый клик
    yearmap.after.assert_called_once()
    args, _ = yearmap.after.call_args
    assert args[0] == 300  # Задержка 300 мс

def test_single_click_filled_week_payload(yearmap):
    """Одинарный клик по неделе с данными → корректный payload."""
    monday = datetime.date(2026, 8, 17)
    _fire_single_now(yearmap, monday)
    yearmap.on_week_pick.assert_called_once()
    w, d = yearmap.on_week_pick.call_args[0]
    assert d == monday

def test_single_click_empty_week_payload(yearmap):
    """Одинарный клик по пустой неделе → корректный payload."""
    monday = datetime.date(2026, 9, 14)
    _fire_single_now(yearmap, monday)
    yearmap.on_week_pick.assert_called_once()
    _, d = yearmap.on_week_pick.call_args[0]
    assert d == monday


# ======================== ДВОЙНОЙ КЛИК ========================

def test_double_click_filled_week(yearmap):
    """Двойной клик по неделе → on_week_dbl, НЕ on_week_pick."""
    _simulate_click(yearmap, w=33, time_offset=0.1) # 0.1 сек назад = двойной клик
    yearmap.on_week_dbl.assert_called_once()
    w, monday = yearmap.on_week_dbl.call_args[0]
    assert 0 <= w <= 52
    assert isinstance(monday, datetime.date)
    yearmap.on_week_pick.assert_not_called()

def test_double_click_empty_week(yearmap):
    """Двойной клик по пустой неделе → on_week_dbl."""
    _simulate_click(yearmap, w=50, time_offset=0.1)
    yearmap.on_week_dbl.assert_called_once()
    yearmap.on_week_pick.assert_not_called()

def test_double_click_cancels_single_timer(yearmap):
    """Двойной клик отменяет таймер одинарного клика."""
    yearmap._single_timer = "prev_timer"
    _simulate_click(yearmap, w=0, time_offset=0.1)
    yearmap.after_cancel.assert_called_once_with("prev_timer")
    yearmap.on_week_dbl.assert_called_once()
    yearmap.on_week_pick.assert_not_called()

def test_slow_second_click_is_new_single(yearmap):
    """Если между кликами прошло > 0.45 сек, это считается новым одинарным кликом."""
    yearmap.after.reset_mock()
    _simulate_click(yearmap, w=0, time_offset=1.0)
    yearmap.after.assert_called()
    yearmap.on_week_dbl.assert_not_called()


# ======================== ПКМ ========================

def test_right_click_syncs_week_and_zoom(yearmap):
    """
    ПКМ по yearmap:
    1. Устанавливает зум на весь год (on_year_zoom).
    2. Синхронизирует неделю (on_week_pick), чтобы обновить weekmap и оркестратор.
    """
    x = X0 + 30 * yearmap._step + yearmap._cell // 2
    y = Y0 + 3 * yearmap._step + yearmap._cell // 2
    event = Mock()
    event.x = x
    event.y = y
    
    yearmap._on_right_click(event)
    
    # Проверка зума на год
    yearmap.on_year_zoom.assert_called_once()
    s, e = yearmap.on_year_zoom.call_args[0]
    assert s == datetime.date(2026, 1, 1)
    assert e == datetime.date(2026, 12, 31)
    
    # Проверка синхронизации недели (КРИТИЧНО для работы оркестратора)
    yearmap.on_week_pick.assert_called_once()
    w, monday = yearmap.on_week_pick.call_args[0]
    assert w == 30
    assert isinstance(monday, datetime.date)


# ======================== КОЛЕСО И КРАЙНИЕ СЛУЧАИ ========================

def test_wheel_changes_year(yearmap):
    """Колесо мыши → on_year_change(delta)."""
    event = Mock()
    event.delta = 120
    yearmap._wheel_lock = 0.0
    yearmap._on_wheel(event)
    yearmap.on_year_change.assert_called_once_with(1)

    event.delta = -120
    yearmap._wheel_lock = 0.0
    yearmap._on_wheel(event)
    yearmap.on_year_change.assert_called_with(-1)

def test_click_outside_grid(yearmap):
    """Клик вне сетки → ничего не вызывается."""
    yearmap.on_week_pick.reset_mock()
    yearmap.on_week_dbl.reset_mock()
    event = Mock()
    event.x = -10
    event.y = -10
    yearmap._on_click(event)
    yearmap.on_week_pick.assert_not_called()
    yearmap.on_week_dbl.assert_not_called()

def test_click_no_year(yearmap):
    """Без года → monday=None → on_week_pick вызывается с None."""
    yearmap._year_start = None
    yearmap.on_week_pick.reset_mock()
    _fire_single_now(yearmap, None)
    yearmap.on_week_pick.assert_called_once()
    _, d = yearmap.on_week_pick.call_args[0]
    assert d is None

def test_right_click_outside_grid(yearmap):
    """ПКМ вне сетки → on_year_zoom и on_week_pick не вызываются."""
    yearmap.on_year_zoom.reset_mock()
    yearmap.on_week_pick.reset_mock()
    event = Mock()
    event.x = -10
    event.y = -10
    yearmap._on_right_click(event)
    yearmap.on_year_zoom.assert_not_called()
    yearmap.on_week_pick.assert_not_called()

def test_yearmap_mouse_wheel_integration(gui_root):
    """
    Интеграционный тест: прокрутка колеса над yearmap должна уведомлять Оркестратора.
    Проверяет, что виджет правильно делегирует событие, а не меняет состояние сам.
    """
    from heatmap import Heatmap
    from unittest.mock import Mock
    import time as _time

    # Создаем реальный виджет Heatmap
    hm = Heatmap(gui_root, db_path=":memory:")
    hm.pack(fill="both", expand=True)
    gui_root.update()
    
    initial_year = hm.year_map.year
    
    # Создаем мок для имитации Оркестратора
    mock_orchestrator = Mock()
    hm.on_year_change = mock_orchestrator

    # 1. Эмулируем событие прокрутки колеса ВВЕРХ (delta > 0)
    event_up = Mock()
    event_up.delta = 120
    hm.year_map._on_wheel(event_up)
    gui_root.update()
    
    # Проверяем, что Оркестратор был уведомлен с delta=1
    mock_orchestrator.assert_called_once_with(1)
    
    # Год НЕ должен был измениться локально (это делает Оркестратор)
    assert hm.year_map.year == initial_year, \
        f"Год не должен меняться локально, было {initial_year}, стало {hm.year_map.year}"
    
    # ⚡ Сбрасываем блокировку колеса, чтобы второй вызов не был проигнорирован
    hm.year_map._wheel_lock = 0.0
    
    # 2. Эмулируем прокрутку ВНИЗ (delta < 0)
    event_down = Mock()
    event_down.delta = -120
    hm.year_map._on_wheel(event_down)
    gui_root.update()
    
    # Проверяем, что Оркестратор был уведомлен с delta=-1
    mock_orchestrator.assert_called_with(-1)