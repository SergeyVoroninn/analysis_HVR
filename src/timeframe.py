"""
timeframe.py — таймфреймы баров и конфигурация отрисовки графиков.

Логика:
  span <= 7 дней    — HOUR1 (1 час), зебра DAY, подписи дни недели
  7 < span <= 31    — HOUR3 (3 часа), зебра DAY, подписи понедельники
  31 < span <= 366  — DAY (день), зебра WEEK, подписи месяцы
  span > 366        — пропорциональный расчет (без календарной привязки)
"""
from __future__ import annotations

import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class TimeFrame(Enum):
    """Таймфреймы для календарных баров."""

    MIN5  = ("5мин",   300)
    HOUR1 = ("1час",   3600)
    HOUR3 = ("3часа",  10800)
    DAY   = ("день",    86400)
    WEEK  = ("неделя", 604800)

    def __init__(self, label: str, seconds: int):
        self.label = label
        self._seconds = seconds
    
    @property
    def bar_size(self) -> float:
        """Размер бара в днях (float)."""
        return self._seconds / 86400.0
    
    def bin_key(self, x: float) -> float:
        """
        x — ordinal (float-день). 
        Возвращает ordinal левого края календарного бара.
        """
        if self is TimeFrame.HOUR1:
            return int(x * 24) / 24
        if self is TimeFrame.HOUR3:
            return int(x * 8) / 8
        if self is TimeFrame.DAY:
            return int(x)
        if self is TimeFrame.WEEK:
            return (int(x) // 7) * 7
        return x
    
    @property
    def zebra(self) -> 'TimeFrame':
        """Таймфрейм для отрисовки зебры."""
        return _ZEBRA_MAP[self]


# Карта зебры: какой таймфрейм использовать для следующего уровня
_ZEBRA_MAP = {
    TimeFrame.HOUR1: TimeFrame.DAY,
    TimeFrame.HOUR3: TimeFrame.DAY,
    TimeFrame.DAY:   TimeFrame.WEEK,
    TimeFrame.WEEK:  TimeFrame.WEEK,
}


@dataclass
class ChartConfig:
    """Конфигурация отрисовки графика для заданного диапазона."""
    bar_tf: TimeFrame
    zebra_tf: TimeFrame
    tick_step_days: int
    tick_format: str
    tick_step_hours: int = 0           # <-- ДОБАВЛЕНО: шаг подписей в часах (0 = не используется)
    is_proportional: bool = False
    proportional_bar_size: Optional[float] = None


def get_chart_config(span_days: float) -> ChartConfig:
    """Возвращает конфигурацию отрисовки для заданного диапазона."""
    # Суточный диапазон (<= 1 день): бар 5 минут, зебра час, подписи каждые 3 часа
    if span_days <= 1:
        return ChartConfig(
            bar_tf=TimeFrame.MIN5,
            zebra_tf=TimeFrame.HOUR1,
            tick_step_days=1,
            tick_format="3hour",
            tick_step_hours=3
        )
    
    # Недельный диапазон (<= 7 дней)
    if span_days <= 7:
        return ChartConfig(
            bar_tf=TimeFrame.HOUR1,
            zebra_tf=TimeFrame.DAY,
            tick_step_days=1,
            tick_format="weekday"
        )
    
    # До месяца (<= 31 день)
    if span_days <= 31:
        return ChartConfig(
            bar_tf=TimeFrame.HOUR3,
            zebra_tf=TimeFrame.DAY,
            tick_step_days=7,
            tick_format="%d.%m"
        )
    
    # До года (включая високосный 366 дней)
    if span_days <= 366:
        return ChartConfig(
            bar_tf=TimeFrame.DAY,
            zebra_tf=TimeFrame.WEEK,
            tick_step_days=30,
            tick_format="%d.%m.%y"
        )
    
    # Больше года: пропорциональный режим
    return ChartConfig(
        bar_tf=TimeFrame.DAY,
        zebra_tf=TimeFrame.WEEK,
        tick_step_days=365,
        tick_format="%Y",
        is_proportional=True
    )


def calc_proportional_bar_size(span_days: float, width_px: float, 
                                target_bar_px: int = 15) -> float:
    """Вычисляет пропорциональный размер бара для span > 366 дней."""
    if width_px < 1:
        width_px = 1
    bars_count = max(10, int(width_px / target_bar_px))
    return span_days / bars_count


def pick_year_step(vspan: float) -> int:
    """Выбирает шаг лет для отрисовки подписей."""
    for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if vspan / (365 * n) <= 12:
            return n
    return 1000