"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).

MetricSpec — описание величины (имя, ось, извлечение значения, цвет).
MetricPlot — виджет одного графика: атлет + диапазон; масштабы авто.
"""
import datetime

import tkinter as tk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_TEXT_DIM,
                   COL_SPINE, COL_TP_YEAR)


class _FrozenCanvas(FigureCanvasTkAgg):
    """Канвас, который не перерисовывается, пока заморожен (ресайз окна)."""

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
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[mpl] set_frozen={frozen}", flush=True)
        self._frozen = frozen


class MetricSpec:
    """Описание отображаемой величины."""

    def __init__(self, key, name, ylabel, value, color=None):
        self.key = key
        self.name = name
        self.ylabel = ylabel
        self.value = value        # callable(record) -> float | None
        self.color = color        # str | callable(v) -> color


class MetricPlot(tk.Frame):
    """График одного параметра: атлет + диапазон [start, end]."""

    def __init__(self, master, spec, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.spec = spec
        self.db_path = db_path or get_db_path()
        self._athlete = None
        self._start = None
        self._end = None
        self._values = []

        self.fig = Figure(dpi=100)
        self.fig.patch.set_facecolor(COL_BG_DARK)
        self.ax = self.fig.add_subplot(111)
        self.canvas = _FrozenCanvas(self.fig, master=self)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(background=COL_BG_WIDGET)
        self.widget.pack(side="top", fill="x")
        self.fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.18)
        self._style()

    def set_frozen(self, frozen):
        """Заморозить перерисовку на время ресайза окна."""
        self.canvas.set_frozen(frozen)

    # ---------------- входы ----------------
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
        self._reload()

    def set_size(self, w, h):
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[mpl] set_size {w}x{h}", flush=True)
        self.widget.configure(width=w, height=h)

    # ---------------- данные ----------------
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

    # ---------------- отрисовка ----------------
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

        span = max(1, (self._end - self._start).days)

        if span > 120:                                # недели
            bw = 5.6
            def key(dt): return ((dt.date() - self._start).days // 7) * 7
        elif span > 2:                                # дни
            bw = 0.8
            def key(dt): return (dt.date() - self._start).days
        else:                                         # 3-часовые блоки
            bw = 0.1
            def key(dt): return ((dt - self._start).days +
                                 (dt.hour // 3) * 0.125)

        agg = {}
        for dt, v in self._values:
            agg.setdefault(key(dt), []).append(v)
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs]

        c = self.spec.color
        colors = [c(v) for v in ys] if callable(c) else (c or COL_TP_YEAR)
        ax.bar(xs, ys, width=bw, color=colors, align="edge")

        ax.set_xlim(0, span)
        self._set_x_ticks(span)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)
        ax.set_title(f"{self.spec.name} "
                     f"({self._start:%d.%m.%y}–{self._end:%d.%m.%y})",
                     color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    def _set_x_ticks(self, span):
        for step in (1, 2, 7, 14, 30, 60, 90, 180, 365):
            if span / step <= 9:
                break
        ticks, names = [], []
        d = self._start
        while (d - self._start).days <= span:
            ticks.append((d - self._start).days)
            names.append(d.strftime("%d.%m.%y") if span > 350
                         else d.strftime("%d.%m"))
            d += datetime.timedelta(days=step)
        self.ax.set_xticks(ticks)
        self.ax.set_xticklabels(names, fontsize=7)