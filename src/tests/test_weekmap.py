"""Тесты кликов по weekmap: одинарный/двойной по зелёной/пустой ячейке."""
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
    wm._block_map = {
        ("2026-08-17", 0): {"count": 1, "worst": None},  # пн 00-03 заполнена
        ("2026-08-19", 2): {"count": 3, "worst": None},  # ср 06-09 заполнена
        ("2026-08-21", 5): {"count": 1, "worst": "crit"},  # пт 15-18 заполнена
    }
    wm._cells, wm._colors = {}, {}
    wm._click_t = 0.0
    wm._click_d = -1
    wm._click_b = -1
    wm._single_timer = None
    wm.after = Mock(return_value="timer_123")
    return wm


def _fire_single_now(weekmap, day, block):
    """Прямой вызов _fire_single, чтобы не ждать 350мс таймера."""
    weekmap._fire_single(day, block)


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_green_cell(weekmap):
    """Одинарный клик по зелёной ячейке → on_pick(day, block) с номером блока."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 17), 0)
    weekmap.on_pick.assert_called_once()
    day, block = weekmap.on_pick.call_args[0]
    assert day == datetime.date(2026, 8, 17)
    assert block == 0


def test_single_click_green_cell_crit(weekmap):
    """Одинарный клик по критической ячейке → on_pick с номером блока."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 21), 5)
    weekmap.on_pick.assert_called_once()
    _, block = weekmap.on_pick.call_args[0]
    assert block == 5


def test_single_click_empty_cell(weekmap):
    """Одинарный клик по пустой ячейке → on_pick(day, None)."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 18), None)
    weekmap.on_pick.assert_called_once()
    day, block = weekmap.on_pick.call_args[0]
    assert day == datetime.date(2026, 8, 18)
    assert block is None


def test_single_click_empty_cell_outside_data(weekmap):
    """Одинарный клик по ячейке без записей → block=None."""
    _fire_single_now(weekmap, datetime.date(2026, 8, 18), None)
    weekmap.on_pick.assert_called_once()
    _, block = weekmap.on_pick.call_args[0]
    assert block is None


# ======================== ДВОЙНОЙ КЛИК (через _on_click) ========================

def _double_click(weekmap, day, block):
    """Симулирует двойной клик — устанавливаем метки первого клика,
    затем вызываем _on_click с тем же d,b — детектируется как двойной."""
    x = X0 + day * weekmap._step + weekmap._cell // 2
    y = Y0 + block * weekmap._step + weekmap._cell // 2
    event = Mock()
    event.x = x
    event.y = y
    weekmap._click_t = _time.monotonic()  # только что
    weekmap._click_d = day
    weekmap._click_b = block
    weekmap._single_timer = None
    weekmap._on_click(event)


def test_double_click_green_cell(weekmap):
    """Двойной клик по зелёной ячейке → on_day_dbl, НЕ on_pick."""
    _double_click(weekmap, day=2, block=2)
    weekmap.on_day_dbl.assert_called_once()
    day_start, day_end = weekmap.on_day_dbl.call_args[0]
    assert day_start == datetime.date(2026, 8, 19)
    assert day_end == datetime.date(2026, 8, 20)
    weekmap.on_pick.assert_not_called()


def test_double_click_empty_cell(weekmap):
    """Двойной клик по пустой ячейке → on_day_dbl, НЕ on_pick."""
    _double_click(weekmap, day=5, block=7)
    weekmap.on_day_dbl.assert_called_once()
    day_start, day_end = weekmap.on_day_dbl.call_args[0]
    assert day_start == datetime.date(2026, 8, 22)
    assert day_end == datetime.date(2026, 8, 23)
    weekmap.on_pick.assert_not_called()


def test_double_click_does_not_trigger_single(weekmap):
    """Двойной клик не вызывает on_pick (таймер отменён)."""
    _double_click(weekmap, day=0, block=0)
    weekmap.on_day_dbl.assert_called_once()
    weekmap.on_pick.assert_not_called()


# ======================== КРАЙНИЕ СЛУЧАИ ========================

def test_click_outside_grid(weekmap):
    """Клик вне сетки → ничего не вызывается."""
    weekmap.on_pick.reset_mock()
    weekmap.on_day_dbl.reset_mock()
    event = Mock()
    event.x = -10
    event.y = -10
    weekmap._on_click(event)
    weekmap.on_pick.assert_not_called()
    weekmap.on_day_dbl.assert_not_called()


def test_click_no_week_start(weekmap):
    """Если week_start=None → клики игнорируются."""
    weekmap._week_start = None
    weekmap.on_pick.reset_mock()
    weekmap.on_day_dbl.reset_mock()
    event = Mock()
    event.x = X0 + 0 * weekmap._step + weekmap._cell // 2
    event.y = Y0 + 0 * weekmap._step + weekmap._cell // 2
    weekmap._on_click(event)
    weekmap.on_pick.assert_not_called()
    weekmap.on_day_dbl.assert_not_called()