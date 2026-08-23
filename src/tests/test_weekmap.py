"""
Тесты кликов по weekmap: одинарный, двойной, ПКМ, пустые/заполненные ячейки.
Проверяет реальное, актуальное поведение виджета.
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

from weekmap import WeekHeatmap, X0, Y0


@pytest.fixture
def weekmap():
    from database import get_db_path

    wm = WeekHeatmap.__new__(WeekHeatmap)
    wm._cell = 14
    wm._step = 15
    wm._title = Mock()
    wm._title.winfo_reqheight = Mock(return_value=20)
    wm._cnv = Mock()
    wm._cnv.winfo_width = Mock(return_value=200)
    wm._cnv.winfo_height = Mock(return_value=200)
    wm.db_path = get_db_path()
    wm.on_pick = Mock()
    wm.on_day_dbl = Mock()
    wm.on_week_rmb = Mock()
    wm._athlete_id = "test"
    wm._week_start = datetime.date(2026, 8, 17)  # понедельник
    
    # Карта данных: (дата, блок) -> {"count": N, "worst": status}
    wm._block_map = {
        ("2026-08-17", 0): {"count": 1, "worst": None},       # пн 00-03
        ("2026-08-19", 2): {"count": 3, "worst": None},       # ср 06-09
        ("2026-08-21", 5): {"count": 1, "worst": "crit"},     # пт 15-18
    }
    wm._cells, wm._colors = {}, {}
    wm._click_t = 0.0
    wm._click_d = -1
    wm._click_b = -1
    wm._single_timer = None
    wm.after = Mock(return_value="timer_123")
    wm.after_cancel = Mock()
    return wm


def _fire_single_now(weekmap, day, block):
    """Прямой вызов _fire_single для проверки payload колбэка."""
    weekmap._fire_single(day, block)


def _simulate_click(weekmap, day, block, time_offset=0.0):
    """Симулирует событие клика в _on_click."""
    x = X0 + day * weekmap._step + weekmap._cell // 2
    y = Y0 + block * weekmap._step + weekmap._cell // 2
    event = Mock()
    event.x = x
    event.y = y
    
    # Устанавливаем время и координаты предыдущего клика для эмуляции двойного
    weekmap._click_t = _time.monotonic() - time_offset
    weekmap._click_d = day
    weekmap._click_b = block
    
    # ВАЖНО: НЕ сбрасываем _single_timer здесь, чтобы тесты могли задать его вручную!
    
    weekmap._on_click(event)


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_schedules_timer(weekmap):
    """Одинарный клик планирует вызов on_pick через 350 мс."""
    _simulate_click(weekmap, day=0, block=0, time_offset=1.0) # 1 сек назад = новый клик
    weekmap.after.assert_called_once()
    args, _ = weekmap.after.call_args
    assert args[0] == 350  # Задержка 350 мс

def test_single_click_green_cell_payload(weekmap):
    """Проверка payload: клик по зелёной ячейке передает день и номер блока."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 17), 0)
    weekmap.on_pick.assert_called_once()
    day, block = weekmap.on_pick.call_args[0]
    assert day == datetime.date(2026, 8, 17)
    assert block == 0

def test_single_click_green_cell_crit_payload(weekmap):
    """Проверка payload: клик по критической ячейке передает номер блока."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 21), 5)
    weekmap.on_pick.assert_called_once()
    _, block = weekmap.on_pick.call_args[0]
    assert block == 5

def test_single_click_empty_cell_payload(weekmap):
    """Проверка payload: клик по пустой ячейке передает day и block=None."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 18), None)
    weekmap.on_pick.assert_called_once()
    day, block = weekmap.on_pick.call_args[0]
    assert day == datetime.date(2026, 8, 18)
    assert block is None


# ======================== ДВОЙНОЙ КЛИК ========================

def test_double_click_green_cell(weekmap):
    """Двойной клик по ячейке → on_day_dbl, НЕ on_pick."""
    _simulate_click(weekmap, day=2, block=2, time_offset=0.1) # 0.1 сек назад = двойной клик
    weekmap.on_day_dbl.assert_called_once()
    day_start, day_end = weekmap.on_day_dbl.call_args[0]
    assert day_start == datetime.date(2026, 8, 19)
    assert day_end == datetime.date(2026, 8, 20)
    weekmap.on_pick.assert_not_called()

def test_double_click_empty_cell(weekmap):
    """Двойной клик по пустой ячейке → on_day_dbl, НЕ on_pick."""
    _simulate_click(weekmap, day=5, block=7, time_offset=0.1)
    weekmap.on_day_dbl.assert_called_once()
    day_start, day_end = weekmap.on_day_dbl.call_args[0]
    assert day_start == datetime.date(2026, 8, 22)
    assert day_end == datetime.date(2026, 8, 23)
    weekmap.on_pick.assert_not_called()

def test_double_click_cancels_single_timer(weekmap):
    """Двойной клик отменяет таймер одинарного клика."""
    weekmap._single_timer = "prev_timer"
    _simulate_click(weekmap, day=0, block=0, time_offset=0.1)
    weekmap.after_cancel.assert_called_once_with("prev_timer")
    weekmap.on_day_dbl.assert_called_once()
    weekmap.on_pick.assert_not_called()

def test_slow_second_click_is_new_single(weekmap):
    """Если между кликами прошло > 0.45 сек, это считается новым одинарным кликом."""
    weekmap.after.reset_mock()
    # Имитируем, что первый клик был 1 секунду назад
    _simulate_click(weekmap, day=0, block=0, time_offset=1.0)
    # Должен запланировать новый таймер, а не считать двойным кликом
    weekmap.after.assert_called()
    weekmap.on_day_dbl.assert_not_called()


# ======================== ПРАВЫЙ КЛИК (ПКМ) ========================

def test_right_click_calls_week_rmb(weekmap):
    """ПКМ по weekmap → on_week_rmb с диапазоном всей недели (7 дней)."""
    event = Mock()
    event.x = X0 + 50
    event.y = Y0 + 50
    weekmap._on_week_rmb_click(event)
    
    weekmap.on_week_rmb.assert_called_once()
    start, end = weekmap.on_week_rmb.call_args[0]
    assert start == datetime.date(2026, 8, 17)
    assert end == datetime.date(2026, 8, 24)  # 17 + 7 дней

def test_right_click_ignored_if_no_week(weekmap):
    """ПКМ при отсутствии week_start игнорируется."""
    weekmap._week_start = None
    weekmap.on_week_rmb.reset_mock()
    
    event = Mock()
    event.x = 50
    event.y = 50
    weekmap._on_week_rmb_click(event)
    
    weekmap.on_week_rmb.assert_not_called()


# ======================== КРАЙНИЕ СЛУЧАИ ========================

def test_click_outside_grid(weekmap):
    """Клик вне сетки (отрицательные координаты) → ничего не вызывается."""
    weekmap.on_pick.reset_mock()
    weekmap.on_day_dbl.reset_mock()
    
    event = Mock()
    event.x = -10
    event.y = -10
    weekmap._on_click(event)
    
    weekmap.on_pick.assert_not_called()
    weekmap.on_day_dbl.assert_not_called()

def test_click_no_week_start(weekmap):
    """Если week_start=None → любые клики игнорируются."""
    weekmap._week_start = None
    weekmap.on_pick.reset_mock()
    weekmap.on_day_dbl.reset_mock()
    
    event = Mock()
    event.x = X0 + 0 * weekmap._step + weekmap._cell // 2
    event.y = Y0 + 0 * weekmap._step + weekmap._cell // 2
    weekmap._on_click(event)
    
    weekmap.on_pick.assert_not_called()
    weekmap.on_day_dbl.assert_not_called()