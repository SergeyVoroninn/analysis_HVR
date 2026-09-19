"""
timeframe.py — таймфреймы баров и конфигурация отрисовки графиков.

Централизованное управление всеми параметрами отрисовки и локализацией.
"""
from __future__ import annotations

import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Optional

# ==============================================================================
# ЛОКАЛИЗАЦИЯ (Единый источник для всех графических компонентов)
# ==============================================================================
WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


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
        return self._seconds / 86400.0
    
    def bin_key(self, x: float) -> float:
        if self is TimeFrame.HOUR1:
            return int(x * 24) / 24
        if self is TimeFrame.HOUR3:
            return int(x * 8) / 8
        if self is TimeFrame.DAY:
            return int(x)
        if self is TimeFrame.WEEK:
            #  Сдвигаем к ближайшему понедельнику
            d = datetime.date.fromordinal(int(x))
            monday = d - datetime.timedelta(days=d.weekday())
            return monday.toordinal()
        return x


@dataclass
class ChartConfig:
    """Конфигурация отрисовки графика для заданного диапазона."""
    bar_tf: TimeFrame
    zebra_tf: TimeFrame
    tick_step_days: int
    tick_format: str
    tick_step_hours: int = 0                    
    is_proportional: bool = False
    proportional_bar_size: Optional[float] = None
    tick_edge_format: Optional[str] = None      
    tick_inner_format: Optional[str] = None
    weekday_date_on_monday: bool = False
    force_edge_format: bool = True              
    show_month_label: bool = False              # 🔧 ДОБАВЛЕНО: показывать месяц над датой


def get_chart_config(span_days: float) -> ChartConfig:
    """Возвращает конфигурацию отрисовки для заданного диапазона."""
    
    # === Суточный диапазон (<= 1 день) ===
    if span_days <= 1:
        return ChartConfig(
            bar_tf=TimeFrame.MIN5,
            zebra_tf=TimeFrame.HOUR1,
            tick_step_days=1,
            tick_format="3hour",
            tick_step_hours=3,
            tick_edge_format="%d.%m",        
            tick_inner_format="%H:%M",
            force_edge_format=True           
        )
    
    # === Недельный диапазон (1-7 дней) ===
    if span_days <= 7:
        return ChartConfig(
            bar_tf=TimeFrame.HOUR1,
            zebra_tf=TimeFrame.DAY,
            tick_step_days=1,
            tick_format="weekday",
            tick_edge_format="%d.%m",        
            tick_inner_format="weekday",
            force_edge_format=True           
        )
    
    # === Месячный диапазон (7-31 день) ===
    if span_days <= 31:
        return ChartConfig(
            bar_tf=TimeFrame.HOUR3,
            zebra_tf=TimeFrame.DAY,
            tick_step_days=1,
            tick_format="weekday",
            tick_edge_format=None,           
            tick_inner_format="weekday",
            weekday_date_on_monday=True,     
            force_edge_format=False          
        )
    
    # === Диапазон 1-4 месяца (31-120 дней) ===
    if span_days <= 120:
        return ChartConfig(
            bar_tf=TimeFrame.DAY,
            zebra_tf=TimeFrame.WEEK,
            tick_step_days=7,
            tick_format="%d",
            show_month_label=True            # 🔧 Включаем отображение месяца
        )
    
    # === Диапазон 4-12 месяцев (120-366 дней) ===
    if span_days <= 366:
        return ChartConfig(
            bar_tf=TimeFrame.DAY,
            zebra_tf=TimeFrame.WEEK,
            tick_step_days=99999,               
            tick_format="%d",                # Обычные тики показывают число дня
            show_month_label=True            # 🔧 ВКЛЮЧАЕМ: добавляет тики на 1-е число с названием месяца
        )
    
    # === Больше года: пропорциональный режим ===
    return ChartConfig(
        bar_tf=TimeFrame.DAY,
        zebra_tf=TimeFrame.WEEK,
        tick_step_days=365,
        tick_format="%Y",
        is_proportional=True
    )


def calc_proportional_bar_size(span_days: float, width_px: float, target_bar_px: int = 15) -> float:
    if width_px < 1: width_px = 1
    bars_count = max(10, int(width_px / target_bar_px))
    return span_days / bars_count


def pick_year_step(vspan: float) -> int:
    for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if vspan / (365 * n) <= 12:
            return n
    return 1000