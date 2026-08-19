"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).

MetricSpec — описание величины (имя, ось, извлечение значения, цвет).
MetricPlot — виджет одного графика: атлет + диапазон [start, end].

Зум по оси X:
  колесо мыши      — зум к курсору;
  зажать и тянуть  — панорамирование;
  ПКМ              — сброс на весь период;
  двойной клик     — зум до года кликнутого столбика.

view = (lo, hi) — абсолютный видимый диапазон в днях (ordinal, float).
"""
import datetime
import time as _time
import tkinter as tk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_TEXT_DIM,
                   COL_SPINE, COL_TP_YEAR)


class _FrozenCanvas(FigureCanvasTkAgg):

    def __init__(self, figure, master=None):
        super().__init__(figure, master=master)
        self._frozen = False

    def resize(self, event):
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[mpl] resize {event.width}x{event.height} frozen={self._frozen}", flush=True)
        if self._frozen:
            return
        super().resize(event)

    def set_frozen(self, frozen):
        if frozen == self._frozen:
            return
        self._frozen = frozen


class MetricSpec:

    def __init__(self, key, name, ylabel, value, color=None):
        self.key = key
        self.name = name
        self.ylabel = ylabel
        self.value = value
        self.color = color


class MetricPlot(tk.Frame):

    WEEK_BIN_SPAN = 120
    BLOCK_BIN_SPAN = 14

    def __init__(self, master, spec, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.spec = spec
        self.db_path = db_path or get_db_path()
        self._athlete = None
        self._start = None
        self._end = None
        self._values = []
        self.view = None
        self._pan = None
        self._single_timer = None
        self._click_t = 0.0
        self._click_x = 0.0
        self._click_y = 0.0
        self.on_view_changed = None
        self.on_year_pick = None
        self.on_reset = None
        self.on_single_click = None

        self.fig = Figure(dpi=100)
        self.fig.patch.set_facecolor(COL_BG_DARK)
        self.ax = self.fig.add_subplot(111)
        self.canvas = _FrozenCanvas(self.fig, master=self)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(background=COL_BG_WIDGET)
        self.widget.pack(side="top", fill="x")
        self.fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.18)
        self._style()

        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

    def set_frozen(self, frozen):
        self.canvas.set_frozen(frozen)

    @property
    def athlete(self):
        return self._athlete

    @athlete.setter
    def athlete(self, aid):
        self._athlete = aid
        self._start = self._end = None
        self._reload()

    def set_range(self, start, end):
        self._start, self._end = start, end
        self.view = None
        self._reload()

    def set_size(self, w, h):
        self.widget.configure(width=w, height=h)

    def redraw(self):
        self._draw()

    def _reload(self):
        self._values = []
        if not self._athlete:
            self._draw()
            return
        session = get_session(self.db_path)
        try:
            q = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == self._athlete)
            if self._start:
                q = q.filter(ECGRecord.recorded_at >=
                             self._start.isoformat() + " 00:00:00")
            if self._end:
                q = q.filter(ECGRecord.recorded_at <
                             self._end.isoformat() + " 23:59:59")
            for rec in q.all():
                v = self.spec.value(rec)
                if v is not None:
                    self._values.append(
                        (datetime.datetime.fromisoformat(rec.recorded_at), v))
        finally:
            session.close()

        if self._start is None and self._values:
            self._start = min(d for d, _ in self._values).date()
            self._end = max(d for d, _ in self._values).date()
        self._draw()

    def _ord(self, x):
        if isinstance(x, datetime.datetime):
            return x.date().toordinal() + x.hour / 24.0 + x.minute / 1440.0
        if isinstance(x, datetime.date):
            return x.toordinal()
        return float(x)

    def _view_ordinals(self):
        if self.view is not None:
            lo, hi = self.view
            if lo >= 1 and hi > lo:
                return float(lo), float(hi)
        if self._start is None:
            return None
        return float(self._ord(self._start)), float(self._ord(self._end)) + 1

    def _commit_view(self, lo, hi):
        self.view = (float(lo), float(hi))
        if self.on_view_changed:
            self.on_view_changed((float(lo), float(hi)))
        else:
            self._draw()

    def _on_scroll(self, event):
        if event.xdata is None or self._start is None:
            return
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        factor = 0.85 if event.button == "up" else 1.18
        new_span = min(365 * 10, max(0.5, (hi - lo) * factor))
        ratio = (event.xdata - lo) / max(1, hi - lo)
        new_lo = event.xdata - ratio * new_span
        new_hi = new_lo + new_span
        self._commit_view(new_lo, new_hi)

    def _on_press(self, event):
        if event.button == 3:
            self.view = None
            if self.on_reset:
                self.on_reset()
            self._draw()
            return
        if event.button != 1 or event.xdata is None or self._start is None:
            return

        now = _time.monotonic()
        is_dbl = (now - self._click_t < 0.45 and
                  abs(event.x - self._click_x) < 6 and
                  abs(event.y - self._click_y) < 6)
        self._click_t = now
        self._click_x = event.x
        self._click_y = event.y

        if is_dbl:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
                self._single_timer = None
            d = datetime.date.fromordinal(int(event.xdata))
            jan1 = datetime.date(d.year, 1, 1)
            dec31 = datetime.date(d.year, 12, 31)
            self._commit_view(self._ord(jan1), self._ord(dec31) + 1)
            if self.on_year_pick:
                self.on_year_pick(d.year)
            return

        d = datetime.date.fromordinal(int(event.xdata))
        if self.on_single_click:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
            self._single_timer = self.after(300, lambda dd=d: self._fire_single(dd))

        v = self._view_ordinals()
        if v is None:
            return
        self._pan = (event.x, v[0], v[1])

    def _fire_single(self, d):
        self._single_timer = None
        if self.on_single_click:
            self.on_single_click(d)

    def _on_motion(self, event):
        if self._pan is None or event.button != 1:
            return
        x0, lo0, hi0 = self._pan
        width_px = self.ax.get_window_extent().width
        if width_px <= 1:
            return
        span = hi0 - lo0
        dpp = span / width_px
        shift = (x0 - event.x) * dpp
        self._commit_view(lo0 + shift, lo0 + shift + span)

    def _on_release(self, event):
        self._pan = None

    def center_on_week(self, week_start_date):
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        span = hi - lo
        thu = week_start_date + datetime.timedelta(days=3)
        center = self._ord(thu)
        self._commit_view(center - span / 2, center + span / 2)

    def _style(self):
        self.ax.set_facecolor(COL_BG_DARK)
        self.ax.tick_params(colors=COL_TEXT_LIGHT, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(COL_SPINE)

    def _draw(self):
        ax = self.ax
        ax.clear()
        self._style()

        if not self._values or not self._start:
            ax.set_title(f"{self.spec.name}: нет данных",
                         color=COL_TEXT_DIM, fontsize=9)
            self.canvas.draw_idle()
            return

        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        vspan = max(1, hi - lo)

        if vspan > self.WEEK_BIN_SPAN:
            bw = 5.6
            def key(x): return int(x // 7) * 7
        elif vspan > self.BLOCK_BIN_SPAN:
            bw = 0.8
            def key(x): return int(x)
        else:
            bw = 0.1
            def key(x): return int(x * 8) / 8

        agg = {}
        for dt, vv in self._values:
            x = self._ord(dt)
            if not (lo <= x < hi):
                continue
            agg.setdefault(key(x), []).append(vv)
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs]

        if vspan > self.WEEK_BIN_SPAN:
            self._shade_months(ax, lo, hi)
        elif vspan > self.BLOCK_BIN_SPAN:
            self._shade_weeks(ax, lo, hi)
        else:
            self._shade_days(ax, lo, hi)

        c = self.spec.color
        colors = [c(v) for v in ys] if callable(c) else (c or COL_TP_YEAR)
        ax.bar(xs, ys, width=bw, color=colors, align="edge", zorder=2)

        ax.set_xlim(lo, hi)
        # ось Y — по максимуму видимого диапазона (не «залипает» на прошлом)
        if ys:
            ymax = max(ys) or 1
            ax.set_ylim(0, ymax * 1.1)
        self._set_x_ticks(lo, hi, vspan)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)

        d0 = datetime.date.fromordinal(max(1, int(lo)))
        d1 = datetime.date.fromordinal(max(1, int(hi)))
        if vspan > 350:
            title = f"{self.spec.name} ({d0:%d.%m.%y}–{d1:%d.%m.%y})"
        else:
            title = f"{self.spec.name} ({d0:%d.%m}–{d1:%d.%m})"
        ax.set_title(title, color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    def _set_x_ticks(self, lo, hi, vspan):
        if vspan > self.WEEK_BIN_SPAN:
            self._set_month_ticks(lo, hi)
        elif vspan > self.BLOCK_BIN_SPAN:
            self._set_week_ticks(lo, hi)
        else:
            self._set_day_ticks(lo, hi)

    def _set_month_ticks(self, lo, hi):
        months = ["янв", "фев", "мар", "апр", "май", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек"]
        d = datetime.date.fromordinal(max(1, int(lo))).replace(day=1)
        ticks, names = [], []
        while True:
            x = self._ord(d)
            if x > hi:
                break
            if x >= lo - 1e-9:
                ticks.append(x)
                names.append(str(d.year) if d.month == 1 else months[d.month - 1])
            if d.month == 12:
                d = datetime.date(d.year + 1, 1, 1)
            else:
                d = datetime.date(d.year, d.month + 1, 1)
        self.ax.set_xticks(ticks)
        self.ax.set_xticklabels(names, fontsize=7)

    def _set_week_ticks(self, lo, hi):
        d = datetime.date.fromordinal(max(1, int(lo)))
        d -= datetime.timedelta(days=d.weekday())
        ticks, names = [], []
        while True:
            x = self._ord(d)
            if x > hi:
                break
            if x >= lo - 1e-9:
                ticks.append(x)
                names.append(f"{d.day:02d}.{d.month:02d}")
            d += datetime.timedelta(days=7)
        self.ax.set_xticks(ticks)
        self.ax.set_xticklabels(names, fontsize=7)

    def _set_day_ticks(self, lo, hi):
        days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        d = datetime.date.fromordinal(max(1, int(lo)))
        ticks, names = [], []
        while True:
            x = self._ord(d)
            if x > hi:
                break
            if x >= lo - 1e-9:
                ticks.append(x)
                names.append(days[d.weekday()])
            d += datetime.timedelta(days=1)
        self.ax.set_xticks(ticks)
        self.ax.set_xticklabels(names, fontsize=7)

    def _shade_months(self, ax, lo, hi):
        lo = max(1, int(lo))
        d = datetime.date.fromordinal(lo).replace(day=1)
        while True:
            x0 = self._ord(d)
            if x0 > hi:
                break
            ny, nm = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
            x1 = self._ord(datetime.date(ny, nm, 1))
            if (d.year * 12 + d.month) % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            d = datetime.date(ny, nm, 1)

    def _shade_weeks(self, ax, lo, hi):
        lo = max(1, int(lo))
        d = datetime.date.fromordinal(lo)
        d -= datetime.timedelta(days=d.weekday())
        while True:
            x0 = self._ord(d)
            if x0 > hi:
                break
            x1 = x0 + 7
            if d.isocalendar()[1] % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            d += datetime.timedelta(days=7)

    def _shade_days(self, ax, lo, hi):
        lo = max(1, int(lo))
        d = datetime.date.fromordinal(lo)
        while True:
            x0 = self._ord(d)
            if x0 > hi:
                break
            x1 = x0 + 1
            if d.toordinal() % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            d += datetime.timedelta(days=1)