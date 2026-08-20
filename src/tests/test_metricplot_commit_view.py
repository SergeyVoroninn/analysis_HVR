# tests/test_metricplot_commit_view.py
import pytest
from unittest.mock import Mock, MagicMock
from metricplot import MetricPlot, MetricSpec


class TestCommitView:
    """Тесты коррекции span в _commit_view."""

    def setup_method(self):
        """Создаём MetricPlot с mock-канвасом."""
        self.spec = MetricSpec("test", "Test", "unit", lambda r: r.value)
        # Mock master (Tk root)
        self.master = Mock()
        self.master.winfo_width = Mock(return_value=1000)
        # Создаём plot (без реального Tk)
        self.plot = MetricPlot.__new__(MetricPlot)
        self.plot.spec = self.spec
        self.plot._current_tf = None
        self.plot.MIN_BAR_PX = 4
        self.plot.MAX_BAR_PX = 40
        # Mock matplotlib ax
        self.plot.ax = Mock()
        self.plot.ax.get_window_extent = Mock(return_value=MagicMock(width=1000))
        self.plot.view = None
        self.plot.on_view_changed = None
        self.plot._draw = Mock()

    def test_expands_span_when_bars_too_narrow(self):
        """Если бары уже MIN_BAR_PX — span растягивается."""
        lo, hi = 0, 10  # span=10
        self.plot._commit_view(lo, hi)
        # После коррекции span должен увеличиться
        new_lo, new_hi = self.plot.view
        assert (new_hi - new_lo) > 10

    def test_shrinks_span_when_bars_too_wide(self):
        """Если бары шире MAX_BAR_PX — span сжимается."""
        lo, hi = 0, 0.1  # span=0.1
        self.plot._commit_view(lo, hi)
        # После коррекции span должен уменьшиться
        new_lo, new_hi = self.plot.view
        assert (new_hi - new_lo) < 0.1

    def test_no_change_when_bars_in_range(self):
        """Если бары в [MIN_BAR_PX, MAX_BAR_PX] — span не меняется."""
        lo, hi = 0, 365  # span=365, width=1000 → target ∈ [1.46, 14.6] → DAY (1)
        self.plot._commit_view(lo, hi)
        new_lo, new_hi = self.plot.view
        # span должен остаться ~365 (возможна малая коррекция из-за округления)
        assert abs((new_hi - new_lo) - 365) < 1