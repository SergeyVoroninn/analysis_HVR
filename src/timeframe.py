"""
timeframe.py — фиксированные таймфреймы баров (от 5 секунд до 100 лет).

zebra возвращает (kind, param):
  kind='tf'    — границы по TimeFrame param;
  kind='years' — границы каждые param лет (десятилетия, века…).
"""
import datetime
from enum import Enum

# ВАЖНО: словари вне класса — Python 3.14 иначе считает их членами Enum
_NAMED_SIZES = {"month": 30, "quarter": 91,
                "1year": 365, "2year": 730, "5year": 1826,
                "10year": 3652, "20year": 7305,
                "50year": 18262, "100year": 36525}

_YEAR_EVERY = {"1year": 1, "2year": 2, "5year": 5, "10year": 10,
               "20year": 20, "50year": 50, "100year": 100}


class TimeFrame(Enum):
    SEC5    = ("5сек",    5)
    MIN1    = ("1мин",    60)
    MIN5    = ("5мин",    300)
    MIN30   = ("30мин",   1800)
    HOUR3   = ("3часа",   10800)
    DAY     = ("день",    86400)
    WEEK    = ("неделя",  604800)
    MONTH   = ("месяц",   "month")
    QUARTER = ("квартал", "quarter")
    YEAR    = ("год",     "1year")
    YEAR2   = ("2года",   "2year")
    YEAR5   = ("5лет",    "5year")
    YEAR10  = ("10лет",   "10year")
    YEAR20  = ("20лет",   "20year")
    YEAR50  = ("50лет",   "50year")
    YEAR100 = ("100лет",  "100year")

    def __init__(self, label, sec_or_name):
        self.label = label
        self._sec = sec_or_name

    def bar_size(self):
        if isinstance(self._sec, int):
            return self._sec / 86400.0
        return _NAMED_SIZES[self._sec]

    def bin_key(self, x):
        """x — ordinal (float-день). Возвращает ordinal левого края бара."""
        if self is TimeFrame.SEC5:    return round(x * 17280) / 17280
        if self is TimeFrame.MIN1:    return round(x * 1440) / 1440
        if self is TimeFrame.MIN5:    return int(x * 288) / 288
        if self is TimeFrame.MIN30:   return int(x * 48) / 48
        if self is TimeFrame.HOUR3:   return int(x * 8) / 8
        if self is TimeFrame.DAY:     return int(x)
        if self is TimeFrame.WEEK:    return (int(x) // 7) * 7
        if self is TimeFrame.MONTH:   return self._month_start(x)
        if self is TimeFrame.QUARTER: return self._quarter_start(x)
        return self._year_start(x, _YEAR_EVERY[self._sec])

    # ---------------- зебра ----------------
    @property
    def zebra(self):
        return {
            TimeFrame.SEC5:    ("tf", TimeFrame.MIN1),
            TimeFrame.MIN1:    ("tf", TimeFrame.MIN30),
            TimeFrame.MIN5:    ("tf", TimeFrame.HOUR3),
            TimeFrame.MIN30:   ("tf", TimeFrame.HOUR3),
            TimeFrame.HOUR3:   ("tf", TimeFrame.DAY),
            TimeFrame.DAY:     ("tf", TimeFrame.WEEK),
            TimeFrame.WEEK:    ("tf", TimeFrame.MONTH),
            TimeFrame.MONTH:   ("tf", TimeFrame.QUARTER),
            TimeFrame.QUARTER: ("tf", TimeFrame.YEAR),
            TimeFrame.YEAR:    ("years", 10),
            TimeFrame.YEAR2:   ("years", 20),
            TimeFrame.YEAR5:   ("years", 50),
            TimeFrame.YEAR10:  ("years", 100),
            TimeFrame.YEAR20:  ("years", 200),
            TimeFrame.YEAR50:  ("years", 500),
            TimeFrame.YEAR100: ("years", 1000),
        }[self]

    # ---------------- утилиты ----------------
    @staticmethod
    def _month_start(x):
        d = datetime.date.fromordinal(max(1, int(x))).replace(day=1)
        return d.toordinal()

    @staticmethod
    def _quarter_start(x):
        d = datetime.date.fromordinal(max(1, int(x)))
        m = ((d.month - 1) // 3) * 3 + 1
        return datetime.date(d.year, m, 1).toordinal()

    @staticmethod
    def _year_start(x, every=1):
        d = datetime.date.fromordinal(max(1, int(x)))
        y = max(1, d.year - (d.year % every))
        return datetime.date(y, 1, 1).toordinal()


def pick_timeframe(span_days, width_px, min_bar_px=4, max_bar_px=40):
    """Самый крупный таймфрейм, где бар ∈ [min_bar_px, max_bar_px] пикселей."""
    if width_px < 1:
        width_px = 1
    target_min = span_days / (width_px / min_bar_px)
    target_max = span_days / (width_px / max_bar_px)

    candidates = [tf for tf in TimeFrame
                  if target_min <= tf.bar_size() <= target_max]
    if candidates:
        return max(candidates, key=lambda t: t.bar_size())
    if max(tf.bar_size() for tf in TimeFrame) < target_min:
        return TimeFrame.YEAR100
    return TimeFrame.SEC5