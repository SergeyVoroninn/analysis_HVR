"""Тесты кликов по yearmap: одинарный/двойной/ПКМ, заполненные/пустые недели."""
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
    wm._click_t = 0.0
    wm._click_w = -1
    wm._single_timer = None
    # yearmap — tk.Canvas, нужен after
    wm.after = Mock(return_value="timer_123")
    wm.coords = Mock()
    wm.delete = Mock()
    wm.itemconfigure = Mock()
    wm.create_rectangle = Mock()
    wm.create_text = Mock()
    wm.config = Mock()
    return wm


def _fire_single_now(yearmap, monday):
    yearmap._fire_week_pick(monday)


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_filled_week(yearmap):
    """Одинарный клик по неделе с данными → on_week_pick(monday)."""
    monday = datetime.date(2026, 8, 17)
    _fire_single_now(yearmap, monday)
    yearmap.on_week_pick.assert_called_once()
    w, d = yearmap.on_week_pick.call_args[0]
    assert d == monday


def test_single_click_empty_week(yearmap):
    """Одинарный клик по пустой неделе → on_week_pick всё равно вызывается с monday."""
    monday = datetime.date(2026, 9, 14)
    _fire_single_now(yearmap, monday)
    yearmap.on_week_pick.assert_called_once()
    _, d = yearmap.on_week_pick.call_args[0]
    assert d == monday


# ======================== ДВОЙНОЙ КЛИК (через _on_click) ========================

def _double_click(yearmap, w):
    x = X0 + w * yearmap._step + yearmap._cell // 2
    event = Mock()
    event.x = x
    event.y = Y0 + 3 * yearmap._step + yearmap._cell // 2
    yearmap._click_t = _time.monotonic()
    yearmap._click_w = w
    yearmap._single_timer = None
    yearmap._on_click(event)


def test_double_click_filled_week(yearmap):
    """Двойной клик по неделе → on_week_dbl(week, monday), НЕ on_week_pick."""
    _double_click(yearmap, w=33)  # 33-я неделя ≈ 17.08.2026
    yearmap.on_week_dbl.assert_called_once()
    w, monday = yearmap.on_week_dbl.call_args[0]
    assert 0 <= w <= 52
    assert isinstance(monday, datetime.date)
    yearmap.on_week_pick.assert_not_called()


def test_double_click_empty_week(yearmap):
    """Двойной клик по пустой неделе → on_week_dbl."""
    _double_click(yearmap, w=50)
    yearmap.on_week_dbl.assert_called_once()
    yearmap.on_week_pick.assert_not_called()


def test_double_click_does_not_trigger_single(yearmap):
    """Двойной клик не вызывает on_week_pick (таймер отменён)."""
    _double_click(yearmap, w=0)
    yearmap.on_week_dbl.assert_called_once()
    yearmap.on_week_pick.assert_not_called()


# ======================== ПКМ ========================

def test_right_click_sets_year_zoom(yearmap):
    """ПКМ по yearmap → on_year_zoom(start, end) на весь год."""
    x = X0 + 30 * yearmap._step + yearmap._cell // 2
    y = Y0 + 3 * yearmap._step + yearmap._cell // 2
    event = Mock()
    event.x = x
    event.y = y
    yearmap._on_right_click(event)
    yearmap.on_year_zoom.assert_called_once()
    s, e = yearmap.on_year_zoom.call_args[0]
    assert s == datetime.date(2026, 1, 1)
    assert e == datetime.date(2026, 12, 31)


# ======================== КОЛЕСО ========================

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


# ======================== КРАЙНИЕ СЛУЧАИ ========================

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
    """Без года → monday=None → on_week_pick может не сработать корректно."""
    yearmap._year_start = None
    yearmap.on_week_pick.reset_mock()
    _fire_single_now(yearmap, None)
    yearmap.on_week_pick.assert_called_once()
    _, d = yearmap.on_week_pick.call_args[0]
    assert d is None


def test_right_click_outside_grid(yearmap):
    """ПКМ вне сетки → on_year_zoom не вызывается."""
    yearmap.on_year_zoom.reset_mock()
    event = Mock()
    event.x = -10
    event.y = -10
    yearmap._on_right_click(event)
    yearmap.on_year_zoom.assert_not_called()