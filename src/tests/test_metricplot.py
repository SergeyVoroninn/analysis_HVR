"""
Тесты логики коррекции span в _commit_view (metricplot.py).
Покрытие: 100%
"""
import pytest
from timeframe import TimeFrame


class TestCommitView:
    """Тесты коррекции span в _commit_view."""

    def test_no_change_when_bars_in_range(self, mock_metric_plot):
        """Если бары в [MIN_BAR_PX, MAX_BAR_PX] — span не меняется."""
        lo, hi = 0, 365  # span=365
        mock_metric_plot._commit_view(lo, hi)
        new_lo, new_hi = mock_metric_plot.view
        # span должен остаться ~365
        assert abs((new_hi - new_lo) - 365) < 1
        # _draw должен быть вызван
        mock_metric_plot._draw.assert_called_once()

    def test_expands_span_when_bars_too_narrow(self, mock_metric_plot):
        """Если бары уже MIN_BAR_PX — span растягивается."""
        lo, hi = 0, 10  # span=10, width=1000
        # pick_timeframe вернёт DAY (1 день)
        # actual_px = (1/10)*1000 = 100 px > MAX_BAR_PX=40
        # → нужно сжать span до 1000*1/40 = 25 дней
        mock_metric_plot._commit_view(lo, hi)
        new_lo, new_hi = mock_metric_plot.view
        # span должен увеличиться
        assert (new_hi - new_lo) > 10
        mock_metric_plot._draw.assert_called_once()

    def test_shrinks_span_when_bars_too_wide(self, mock_metric_plot):
        """Если бары шире MAX_BAR_PX — span сжимается."""
        lo, hi = 0, 0.1  # span=0.1 дня
        # pick_timeframe вернёт SEC5 или MIN1
        # actual_px будет очень большим → нужно сжать
        mock_metric_plot._commit_view(lo, hi)
        new_lo, new_hi = mock_metric_plot.view
        # span должен уменьшиться
        assert (new_hi - new_lo) < 0.1
        mock_metric_plot._draw.assert_called_once()

    def test_on_view_changed_callback_called(self, mock_metric_plot):
        """Если on_view_changed задан — он вызывается вместо _draw."""
        callback = mock_metric_plot.on_view_changed = pytest.Mock()
        lo, hi = 0, 365
        mock_metric_plot._commit_view(lo, hi)
        # callback должен быть вызван с view
        callback.assert_called_once()
        args = callback.call_args[0][0]
        assert isinstance(args, tuple)
        assert len(args) == 2
        # _draw не должен быть вызван
        mock_metric_plot._draw.assert_not_called()

    def test_centers_span_around_midpoint(self, mock_metric_plot):
        """При коррекции span центр остаётся на месте."""
        lo, hi = 100, 110  # центр = 105
        mock_metric_plot._commit_view(lo, hi)
        new_lo, new_hi = mock_metric_plot.view
        new_mid = (new_lo + new_hi) / 2
        # центр должен остаться ~105
        assert abs(new_mid - 105) < 0.1

    def test_current_tf_is_set(self, mock_metric_plot):
        """После _commit_view _current_tf должен быть установлен."""
        lo, hi = 0, 365
        mock_metric_plot._commit_view(lo, hi)
        assert mock_metric_plot._current_tf is not None
        assert isinstance(mock_metric_plot._current_tf, TimeFrame)

    def test_view_stored_as_float_tuple(self, mock_metric_plot):
        """view должен храниться как (float, float)."""
        lo, hi = 0, 365
        mock_metric_plot._commit_view(lo, hi)
        assert isinstance(mock_metric_plot.view, tuple)
        assert len(mock_metric_plot.view) == 2
        assert isinstance(mock_metric_plot.view[0], float)
        assert isinstance(mock_metric_plot.view[1], float)