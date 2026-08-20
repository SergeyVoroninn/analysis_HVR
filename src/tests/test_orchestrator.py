"""Тесты оркестратора: сохранение и восстановление масштаба при смене атлета."""
import datetime
import os
import sys
import pytest
from unittest.mock import Mock, patch

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from orchestrator import AppOrchestrator


@pytest.fixture
def orchestrator():
    hm = Mock()
    hm.year_map._year_start = datetime.date(2026, 1, 1) - datetime.timedelta(days=datetime.date(2026, 1, 1).weekday())
    hm.year = 2026
    hm.week = None

    _zoom = [None]
    redraw_called = [False]

    class FakeCharts:
        _plots = [Mock()]
        on_range_changed = None

        def set_year_pick_callback(self, cb):
            self._year_pick_cb = cb

        def set_reset_callback(self, cb):
            self._reset_cb = cb

        def set_single_click_callback(self, cb):
            self._single_click_cb = cb

        @property
        def zoom(self):
            return _zoom[0]

        @zoom.setter
        def zoom(self, v):
            _zoom[0] = v
            if self.on_range_changed and v is not None:
                self.on_range_changed(*v)

        def redraw(self):
            redraw_called[0] = True

    charts = FakeCharts()
    charts._plots[0]._view_ordinals = Mock(return_value=(100.0, 200.0))
    charts._plots[0]._ord = Mock(side_effect=lambda d: d.toordinal())
    charts._plots[0].view = None
    charts._plots[0]._start = None
    charts._plots[0]._end = None
    charts._plots[0]._reload = Mock()

    settings = Mock()

    orch = AppOrchestrator(hm, charts, settings)
    orch._redraw_called = redraw_called
    return orch, hm, charts, charts._plots[0], settings


# ======================== СОХРАНЕНИЕ ПОСЛЕ ЗУМА ========================

def test_saved_range_after_month_zoom(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    start = datetime.date(2026, 6, 1)
    end = datetime.date(2026, 6, 30)
    orch._handle_month_zoom(start, end)
    # проверяем, что установлен zoom через публичный API
    assert charts.zoom == (start.toordinal(), end.toordinal() + 1)


def test_saved_range_after_year_zoom(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    orch._handle_year_zoom(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    assert charts.zoom == (datetime.date(2026, 1, 1).toordinal(),
                           datetime.date(2026, 12, 31).toordinal() + 1)


def test_saved_range_after_day_dbl(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    day = datetime.date(2026, 8, 17)
    orch._handle_weekmap_day_dbl(day, day + datetime.timedelta(days=1))
    lo, hi = charts.zoom
    assert hi - lo == pytest.approx(1.0)


def test_saved_range_after_week_rmb(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    start = datetime.date(2026, 8, 17)
    end = datetime.date(2026, 8, 24)
    orch._handle_weekmap_week_rmb(start, end)
    lo, hi = charts.zoom
    assert lo == start.toordinal()
    assert hi == end.toordinal()


def test_on_range_changed_sets_saved_range(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    orch._on_range_changed(100.0, 200.0)
    assert orch._saved_range == (100.0, 200.0)


def test_saved_range_reset(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    orch._saved_range = (100.0, 200.0)
    orch._handle_chart_reset()
    assert orch._saved_range is None
    # все графики должны быть очищены
    assert p0._start is None
    assert p0._end is None
    assert p0.view is None
    p0._reload.assert_called_once()


# ======================== ВОССТАНОВЛЕНИЕ ПРИ СМЕНЕ АТЛЕТА ========================

def test_sync_athlete_restores_range(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    orch._saved_range = (300.0, 400.0)
    orch.sync_athlete("new_id")
    assert hm.athlete == "new_id"
    assert charts.zoom == (300.0, 400.0)
    assert orch._redraw_called[0]


def test_sync_athlete_no_saved_range(orchestrator):
    orch, hm, charts, p0, _ = orchestrator
    orch._saved_range = None
    orch._redraw_called[0] = False
    orch.sync_athlete("other_id")
    assert not orch._redraw_called[0]


# ======================== СОХРАНЕНИЕ/ВОССТАНОВЛЕНИЕ СОСТОЯНИЯ ========================

def test_save_state_uses_view_ordinals(orchestrator):
    orch, hm, charts, p0, settings = orchestrator
    p0._view_ordinals = Mock(return_value=(150.0, 250.0))
    orch.save_state("athlete_1")
    settings.set.assert_any_call("athlete_id", "athlete_1")
    settings.set.assert_any_call("zoom", [150.0, 250.0])


def test_save_state_no_range(orchestrator):
    orch, hm, charts, p0, settings = orchestrator
    p0._view_ordinals = Mock(return_value=None)
    orch.save_state("athlete_2")
    settings.set.assert_any_call("zoom", None)


def test_restore_state_sets_range(orchestrator):
    orch, hm, charts, p0, settings = orchestrator
    orch.restore_state("athlete_3", 2026, 20, [400.0, 500.0])
    assert orch._saved_range == (400.0, 500.0)
    # charts.zoom сеттер вызван
    assert charts.zoom == (400.0, 500.0)
    hm.set_selection.assert_called_once_with(year=2026, week=20)


def test_restore_state_no_zoom(orchestrator):
    orch, hm, charts, p0, settings = orchestrator
    orch.restore_state("athlete_4", 2025, 10, None)
    assert orch._saved_range is None
    hm.set_selection.assert_called_once_with(year=2025, week=10)


# ======================== ИНТЕГРАЦИЯ: ПОЛНЫЙ ЦИКЛ СОХРАНЕНИЯ/ВОССТАНОВЛЕНИЯ ========================

def test_full_save_restore_cycle_happy_path(orchestrator):
    """Симулируем полный цикл: зум → save → restore → sync_athlete."""
    orch, hm, charts, p0, _ = orchestrator

    p0._view_ordinals = Mock(return_value=(100.0, 200.0))
    orch._saved_range = (100.0, 200.0)

    # 1. Сохраняем
    settings_mock = Mock()
    orch2 = AppOrchestrator(hm, charts, settings_mock)
    orch2._saved_range = (100.0, 200.0)
    orch2.save_state("athlete_42")
    settings_mock.set.assert_any_call("athlete_id", "athlete_42")
    settings_mock.set.assert_any_call("zoom", [100.0, 200.0])

    # 2. Восстанавливаем
    orch3 = AppOrchestrator(Mock(), Mock(), Mock())
    orch3.restore_state("athlete_42", 2026, 20, [100.0, 200.0])
    assert orch3._saved_range == (100.0, 200.0)