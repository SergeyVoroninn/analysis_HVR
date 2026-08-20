"""
timeframe.py — таймфреймы баров.

Логика:
  span <= 365 дней — календарные бары: 3часа / день / неделя
  span >  365 дней — пропорциональная цена бара (без календарной привязки)
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Tuple, Union


class TimeFrame(Enum):
    """Таймфреймы для календарных баров (span <= 365 дней)."""
    
    HOUR3 = ("3часа", 10800)
    DAY   = ("день",   86400)
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
        if self is TimeFrame.HOUR3:
            return int(x * 8) / 8            # 24/3 = 8 интервалов в день
        if self is TimeFrame.DAY:
            return int(x)
        if self is TimeFrame.WEEK:
            return (int(x) // 7) * 7
        return x
    
    @property
    def zebra(self) -> Tuple[str, 'TimeFrame']:
        """Возвращает ('tf', next_tf) для отрисовки зебры."""
        return _ZEBRA_MAP[self]


# Карта зебры: какой таймфрейм использовать для следующего уровня
_ZEBRA_MAP = {
    TimeFrame.HOUR3: ("tf", TimeFrame.DAY),
    TimeFrame.DAY:   ("tf", TimeFrame.WEEK),
    TimeFrame.WEEK:  ("tf", TimeFrame.WEEK),  # для недели зебра по неделям
}


def pick_calendar_timeframe(span_days: float, width_px: float, 
                            min_bar_px: int = 6, max_bar_px: int = 40) -> TimeFrame:
    """
    Выбирает календарный таймфрейм для span <= 365 дней.
    Самый крупный, где бар помещается в [min_bar_px, max_bar_px] пикселей.
    """
    if width_px < 1:
        width_px = 1
    
    # Вычисляем диапазон размеров бара в днях
    target_min = span_days / (width_px / min_bar_px)
    target_max = span_days / (width_px / max_bar_px)
    
    # Ищем таймфреймы, которые попадают в диапазон
    candidates = [tf for tf in TimeFrame if target_min <= tf.bar_size <= target_max]
    
    if candidates:
        return max(candidates, key=lambda t: t.bar_size)
    
    # Если все слишком мелкие — берем максимальный (WEEK)
    if max(tf.bar_size for tf in TimeFrame) < target_min:
        return TimeFrame.WEEK
    
    # Если все слишком крупные — берем минимальный (HOUR3)
    return TimeFrame.HOUR3


def calc_proportional_bar_size(span_days: float, width_px: float, 
                                target_bar_px: int = 15) -> float:
    """
    Вычисляет пропорциональный размер бара для span > 365 дней.
    
    Args:
        span_days: диапазон данных в днях
        width_px: ширина графика в пикселях
        target_bar_px: целевая ширина бара в пикселях
    
    Returns:
        Размер бара в днях (float)
    """
    if width_px < 1:
        width_px = 1
    
    bars_count = max(10, int(width_px / target_bar_px))
    return span_days / bars_count


def get_year_boundaries(start_ordinal: float, end_ordinal: float, 
                        step_years: int = 1) -> list:
    """
    Вычисляет границы лет для отрисовки зебры и подписей.
    
    Args:
        start_ordinal: начало диапазона (ordinal)
        end_ordinal: конец диапазона (ordinal)
        step_years: шаг в годах (1, 2, 5, 10, ...)
    
    Returns:
        Список ordinal'ов границ лет
    """
    start_year = datetime.date.fromordinal(max(1, int(start_ordinal))).year
    end_year = datetime.date.fromordinal(max(1, int(end_ordinal))).year
    
    # Округляем до шага
    first_year = (start_year // step_years) * step_years
    boundaries = []
    
    year = first_year
    while year <= end_year + step_years:
        boundaries.append(datetime.date(year, 1, 1).toordinal())
        year += step_years
    
    return boundaries


def pick_year_step(vspan: float) -> int:
    """
    Выбирает шаг лет для отрисовки подписей.
    
    Args:
        vspan: диапазон в днях
    
    Returns:
        Шаг в годах (1, 2, 5, 10, 20, ...)
    """
    for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if vspan / (365 * n) <= 12:
            return n
    return 1000