"""Тесты событий MetricPlot: клик, двойной клик, ПКМ, панорамирование."""
import datetime
import os
import sys
import time as _time
import pytest
from unittest.mock import Mock, patch

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from metricplot import MetricPlot, MetricSpec


@pytest.fixture
def plot():
    spec = MetricSpec("test", "Test", "unit", lambda r: r.value)
    p = MetricPlot.__new__(MetricPlot)
    p.spec = spec
    p.db_path = ""
    p._athlete = "test"
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
    p.after = Mock(return_value="timer_ok")
    p.after_cancel = Mock()
    p.ax = Mock()
    p.ax.get_window_extent = Mock(return_value=Mock(width=1000))
    p.fig = Mock()
    p.canvas = Mock()
    p.widget = Mock()
    p._ord = Mock(side_effect=lambda x: x.toordinal() if hasattr(x, 'toordinal') else float(x))
    p._commit_view = Mock()
    p._draw = Mock()
    return p


def _event(button=1, xdata=None, x=100, y=100):
    e = Mock()
    e.button = button
    e.xdata = xdata
    e.x = x
    e.y = y
    return e


# ======================== ОДИНАРНЫЙ КЛИК ========================

def test_single_click_fires_single_callback(plot):
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    assert plot.after.called
    # таймер на 500ms
    args = plot.after.call_args
    assert args[0][0] == 500

def test_single_click_sets_pan(plot):
    plot._view_ordinals = Mock(return_value=(100.0, 200.0))
    plot._on_press(_event(button=1, xdata=738000, x=150, y=100))
    assert plot._pan is not None
    assert plot._pan[0] == 150

def test_single_click_does_not_commit_view(plot):
    plot._on_press(_event(button=1, xdata=738000))
    plot._commit_view.assert_not_called()

def test_single_click_fires_after_delay(plot):
    plot._on_press(_event(button=1, xdata=738000))
    d = datetime.date.fromordinal(int(738000))
    plot._fire_single(d)
    plot.on_single_click.assert_called_once()


# ======================== ДВОЙНОЙ КЛИК ИГНОРИРУЕТСЯ ========================

def test_double_click_does_not_commit_view(plot):
    plot._click_t = _time.monotonic() - 0.1
    plot._click_x = 100
    plot._click_y = 100
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    plot._commit_view.assert_not_called()
    plot.on_single_click.assert_not_called()

def test_double_click_different_position_is_not_double(plot):
    plot._click_t = _time.monotonic() - 0.1
    plot._click_x = 100
    plot._click_y = 100
    plot._on_press(_event(button=1, xdata=738000, x=200, y=200))
    # не двойной клик — пиксели разные
    assert plot.after.called  # таймер установлен

def test_double_click_too_slow_is_not_double(plot):
    plot._click_t = _time.monotonic() - 1.0
    plot._click_x = 100
    plot._click_y = 100
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    assert plot.after.called


def test_right_click_calls_reset(plot):
    plot._on_press(_event(button=3, xdata=738000))
    plot.on_reset.assert_called_once()
    plot._commit_view.assert_not_called()

def test_right_click_clears_tf(plot):
    plot._current_tf = "SOME_TF"
    plot._on_press(_event(button=3))
    assert plot._current_tf is None


# ======================== ГРАНИЧНЫЕ СЛУЧАИ ========================

def test_click_no_xdata_ignored(plot):
    plot._on_press(_event(button=1, xdata=None))
    plot.on_single_click.assert_not_called()
    plot._commit_view.assert_not_called()

def test_click_no_start_ignored(plot):
    plot._start = None
    plot._on_press(_event(button=1, xdata=738000))
    plot.on_single_click.assert_not_called()
    plot._commit_view.assert_not_called()

def test_click_button_2_ignored(plot):
    plot._on_press(_event(button=2, xdata=738000))
    plot.on_single_click.assert_not_called()
    plot.on_reset.assert_not_called()

def test_click_cancels_previous_timer(plot):
    plot._single_timer = "prev_timer"
    plot._on_press(_event(button=1, xdata=738000))
    plot.after_cancel.assert_called_once_with("prev_timer")


# ======================== ПАНОРАМИРОВАНИЕ ========================

def test_motion_pans_view(plot):
    plot._view_ordinals = Mock(return_value=(100.0, 200.0))
    plot._on_press(_event(button=1, xdata=738000, x=150, y=100))
    assert plot._pan is not None

    # движение
    event = _event(button=1, x=200)
    plot._on_motion(event)
    plot._commit_view.assert_called()
    lo, hi = plot._commit_view.call_args[0]
    assert lo < hi

def test_motion_without_pan_ignored(plot):
    plot._pan = None
    plot._on_motion(_event(button=1, x=200))
    plot._commit_view.assert_not_called()

def test_motion_wrong_button_ignored(plot):
    plot._pan = (100, 100.0, 200.0)
    plot._on_motion(_event(button=3, x=200))
    plot._commit_view.assert_not_called()

def test_release_clears_pan(plot):
    plot._pan = (100, 100.0, 200.0)
    plot._on_release(_event())
    assert plot._pan is None


# ======================== ПРОВЕРКА ПОРОГА ДВОЙНОГО КЛИКА ========================

def test_double_click_threshold_ignored(plot):
    plot._click_t = _time.monotonic() - 0.1
    plot._click_x = 100
    plot._click_y = 100
    plot.after.reset_mock()
    plot._commit_view.reset_mock()
    plot._on_press(_event(button=1, xdata=738000, x=100, y=100))
    plot._commit_view.assert_not_called()