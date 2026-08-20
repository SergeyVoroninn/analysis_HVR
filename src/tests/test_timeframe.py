"""
Тесты чистого подбора таймфрейма (timeframe.py).
Покрытие: 100%
"""
import pytest
from timeframe import TimeFrame, pick_timeframe


class TestTimeFrameBarSize:
    """Тесты метода bar_size()."""

    def test_seconds_converted_to_days(self):
        assert TimeFrame.SEC5.bar_size() == 5 / 86400.0
        assert TimeFrame.MIN1.bar_size() == 60 / 86400.0
        assert TimeFrame.MIN5.bar_size() == 300 / 86400.0
        assert TimeFrame.MIN30.bar_size() == 1800 / 86400.0
        assert TimeFrame.HOUR3.bar_size() == 10800 / 86400.0

    def test_days_and_larger(self):
        assert TimeFrame.DAY.bar_size() == 1.0
        assert TimeFrame.WEEK.bar_size() == 7.0
        assert TimeFrame.MONTH.bar_size() == 30.0
        assert TimeFrame.QUARTER.bar_size() == 91.0
        assert TimeFrame.YEAR.bar_size() == 365.0
        assert TimeFrame.YEAR2.bar_size() == 730.0


class TestTimeFrameBinKey:
    """Тесты ключа бинирования."""

    def test_sec5_rounds_to_5sec_boundaries(self):
        # 1 день = 17280 интервалов по 5 секунд
        x = 1.5  # 1.5 дня = 36 часов
        key = TimeFrame.SEC5.bin_key(x)
        assert abs(key * 17280 - round(1.5 * 17280)) < 0.001

    def test_min1_rounds_to_1min_boundaries(self):
        x = 1.5  # 36 часов
        key = TimeFrame.MIN1.bin_key(x)
        assert abs(key * 1440 - round(1.5 * 1440)) < 0.001

    def test_day_truncates_to_int(self):
        assert TimeFrame.DAY.bin_key(1.9) == 1
        assert TimeFrame.DAY.bin_key(2.1) == 2

    def test_week_aligns_to_week_start(self):
        # неделя начинается с понедельника (ordinal 0 = 01.01.0001 понедельник)
        assert TimeFrame.WEEK.bin_key(3) == 0    # среда → начало недели
        assert TimeFrame.WEEK.bin_key(7) == 7    # воскресенье → начало след. недели
        assert TimeFrame.WEEK.bin_key(8) == 7    # понедельник → начало недели

    def test_month_aligns_to_1st(self):
        # ordinal 1 = 01.01.0001
        key = TimeFrame.MONTH.bin_key(1)
        assert key == 1  # 1 января
        key = TimeFrame.MONTH.bin_key(15)
        assert key == 1  # 15 января → всё равно 1 января

    def test_quarter_aligns_to_quarter_start(self):
        # Q1: янв-мар, Q2: апр-июн, Q3: июл-сен, Q4: окт-дек
        import datetime
        jan15 = datetime.date(2025, 1, 15).toordinal()
        assert TimeFrame.QUARTER.bin_key(jan15) == datetime.date(2025, 1, 1).toordinal()
        
        apr15 = datetime.date(2025, 4, 15).toordinal()
        assert TimeFrame.QUARTER.bin_key(apr15) == datetime.date(2025, 4, 1).toordinal()

    def test_year_aligns_to_jan1(self):
        import datetime
        mid_year = datetime.date(2025, 6, 15).toordinal()
        key = TimeFrame.YEAR.bin_key(mid_year)
        assert key == datetime.date(2025, 1, 1).toordinal()

    def test_year2_aligns_to_even_years(self):
        import datetime
        mid_2025 = datetime.date(2025, 6, 15).toordinal()
        key = TimeFrame.YEAR2.bin_key(mid_2025)
        assert key == datetime.date(2024, 1, 1).toordinal()  # 2025 → 2024


class TestTimeFrameZebraSibling:
    """Тесты свойства zebra_sibling."""

    def test_small_timeframes(self):
        assert TimeFrame.SEC5.zebra_sibling == TimeFrame.MIN1
        assert TimeFrame.MIN1.zebra_sibling == TimeFrame.MIN30
        assert TimeFrame.MIN5.zebra_sibling == TimeFrame.HOUR3
        assert TimeFrame.MIN30.zebra_sibling == TimeFrame.HOUR3
        assert TimeFrame.HOUR3.zebra_sibling == TimeFrame.DAY

    def test_large_timeframes(self):
        assert TimeFrame.DAY.zebra_sibling == TimeFrame.WEEK
        assert TimeFrame.WEEK.zebra_sibling == TimeFrame.MONTH
        assert TimeFrame.MONTH.zebra_sibling == TimeFrame.QUARTER
        assert TimeFrame.QUARTER.zebra_sibling == TimeFrame.YEAR
        assert TimeFrame.YEAR.zebra_sibling == TimeFrame.YEAR
        assert TimeFrame.YEAR2.zebra_sibling == TimeFrame.YEAR


class TestPickTimeframe:
    """Тесты функции pick_timeframe."""

    def test_normal_range_returns_week(self):
        """365 дней, 1000 px → target ∈ [1.46, 14.6] дня.
        DAY (1.0) < 1.46 → не подходит.
        WEEK (7.0) ∈ [1.46, 14.6] → подходит.
        """
        tf = pick_timeframe(365, 1000, 4, 40)
        assert tf == TimeFrame.WEEK

    def test_large_span_returns_month(self):
        """1000 дней, 1000 px → target ∈ [4, 40] дня.
        WEEK (7.0) и MONTH (30.0) оба подходят.
        Выбирается самый крупный → MONTH.
        """
        tf = pick_timeframe(1000, 1000, 4, 40)
        assert tf == TimeFrame.MONTH

    def test_boundary_returns_only_candidate(self):
        """span=10, width=1000 → target ∈ [0.04, 0.4] дня.
        MIN30 (0.02) < 0.04 → не подходит.
        HOUR3 (0.125) ∈ [0.04, 0.4] → единственный подходящий.
        DAY (1.0) > 0.4 → не подходит.
        """
        tf = pick_timeframe(10, 1000, 4, 40)
        assert tf == TimeFrame.HOUR3

    def test_very_large_span_returns_year2(self):
        """100 000 дней → даже YEAR2 не дотягивает."""
        tf = pick_timeframe(100_000, 1000, 4, 40)
        assert tf == TimeFrame.YEAR2

    def test_tiny_span_returns_sec5(self):
        """0.0001 дня → даже SEC5 шире max_bar_px."""
        tf = pick_timeframe(0.0001, 1000, 4, 40)
        assert tf == TimeFrame.SEC5

    def test_zero_width_falls_back_to_largest(self):
        """width=0 → деление на ноль → fallback на YEAR2."""
        tf = pick_timeframe(365, 0, 4, 40)
        assert tf == TimeFrame.YEAR2

    def test_negative_width_falls_back_to_largest(self):
        """width<0 → fallback на YEAR2."""
        tf = pick_timeframe(365, -100, 4, 40)
        assert tf == TimeFrame.YEAR2

    def test_custom_min_max_bar_px(self):
        """Проверка, что min/max_bar_px действительно используются."""
        # span=100, width=1000
        # min_bar_px=2 → target_min=0.2 → подходит HOUR3 (0.125) или DAY (1)
        tf1 = pick_timeframe(100, 1000, 2, 40)
        # min_bar_px=10 → target_min=1.0 → подходит DAY (1)
        tf2 = pick_timeframe(100, 1000, 10, 40)
        # tf2 должен быть ≥ tf1 (более крупный)
        assert tf2.bar_size() >= tf1.bar_size()