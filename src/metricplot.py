"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).

MetricSpec — описание величины (имя, ось, извлечение значения, цвет).
MetricPlot — виджет одного графика: атлет + диапазон [start, end].

Зум по оси X (как в app.py):
  колесо мыши      — зум к курсору;
  зажать и тянуть  — панорамирование;
  ПКМ              — сброс на весь период.
Окно видимости хранится в self.view = (lo, hi) в днях от начала данных
(None = весь период). Масштаб общий для всех графиков — задаётся через
ChartsPanel.zoom.

Нет привязки к диапазону данных: окно можно увести в прошлое/будущее,
пустые бины просто не рисуются, зебра — до hi.
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

    # пороги детализации (дней видимого окна):
    WEEK_BIN_SPAN = 120    # больше  — бары по неделям,  зебра по месяцам
    BLOCK_BIN_SPAN = 14    # <=14    — бары по 3 часа,   зебра по дням
                           # 14..120 — бары по дням,     зебра по неделям

    def __init__(self, master, spec, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.spec = spec
        self.db_path = db_path or get_db_path()
        self._athlete = None
        self._start = None
        self._end = None
        self._values = []
        self.view = None           # (lo, hi) в днях от _start; None = весь период
        self._pan = None
        self.on_view_changed = None    # callback(view) — синхронизация с другими графиками

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
        """Заморозить перерисовку на время ресайза окна."""
        self.canvas.set_frozen(frozen)

    # ---------------- входы ----------------
    @property
    def athlete(self):
        return self._athlete

    @athlete.setter
    def athlete(self, aid):
        """При смене атлета view НЕ сбрасывается — окно сохраняется."""
        self._athlete = aid
        self._start = self._end = None
        self._reload()

    def set_range(self, start, end):
        self._start, self._end = start, end
        self.view = None
        self._reload()

    def set_size(self, w, h):
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[mpl] set_size {w}x{h}", flush=True)
        self.widget.configure(width=w, height=h)

    def redraw(self):
        self._draw()

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

    # ---------------- окно видимости ----------------
    def _full_span(self):
        return max(1, (self._end - self._start).days)

    def _clamp_view(self):
        """Окно свободно в обе стороны: никакой привязки к данным."""
        if self.view is None:
            span = self._full_span()
            return 0.0, float(span)
        lo, hi = self.view
        span = hi - lo
        if span < 0.5:
            span = self._full_span()
            return 0.0, float(span)
        return lo, lo + span

    # ---------------- зум ----------------
    def _commit_view(self, view):
        """Применяет окно видимости: себе + всем соседям через callback."""
        self.view = view
        if self.on_view_changed:
            self.on_view_changed(view)
        else:
            self._draw()

    def _on_scroll(self, event):
        if event.xdata is None:
            return
        lo, hi = self._clamp_view()
        factor = 0.85 if event.button == "up" else 1.18
        new_span = min(365.0 * 10, max(0.2, (hi - lo) * factor))
        ratio = (event.xdata - lo) / (hi - lo)
        new_lo = event.xdata - ratio * new_span
        new_hi = new_lo + new_span
        self._commit_view((new_lo, new_hi))

    def _on_press(self, event):
        if event.button == 3:
            self._commit_view(None)
            return
        if event.button != 1 or event.xdata is None:
            return
        lo, hi = self._clamp_view()
        self._pan = (event.x, lo, hi)

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
        lo, hi = lo0 + shift, lo0 + shift + span
        self._commit_view((lo, hi))

    def _on_release(self, event):
        self._pan = None

    # ---------------- центрирование по неделе ----------------
    def center_on_week(self, week_start_date):
        """Среда недели — ровно в центре при любом масштабе.
        Нет привязки к данным: пустота слева/справа — ок."""
        if self._start is None:
            return
        wed = week_start_date + datetime.timedelta(days=2)
        center = (wed - self._start).days
        lo, hi = self._clamp_view()
        span = hi - lo
        new_lo = center - span / 2.0
        new_hi = new_lo + span
        self._commit_view((new_lo, new_hi))

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

        lo, hi = self._clamp_view()
        vspan = max(0.5, hi - lo)

        # режим бинирования по видимому окну
        if vspan > self.WEEK_BIN_SPAN:
            bw = 5.6
            def key(x): return int(x // 7) * 7
        elif vspan > self.BLOCK_BIN_SPAN:
            bw = 0.8
            def key(x): return int(x)
        else:
            bw = 0.1
            def key(x): return round(x * 8) / 8     # 3-часовые блоки

        agg = {}
        start_dt = datetime.datetime.combine(self._start, datetime.time())
        for dt, v in self._values:
            x = (dt - start_dt).total_seconds() / 86400.0
            if not (lo <= x < hi):
                continue
            agg.setdefault(key(x), []).append(v)
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs]

        # зебра фона
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
        self._set_x_ticks(lo, hi, vspan)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)
        ax.set_title(f"{self.spec.name} "
                     f"({self._start:%d.%m.%y}–{self._end:%d.%m.%y})",
                     color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    def _set_x_ticks(self, lo, hi, vspan):
        for step in (0.125, 0.25, 0.5, 1, 2, 7, 14, 30, 60, 90, 180, 365):
            if vspan / step <= 9:
                break

        base = datetime.datetime.combine(self._start, datetime.time())
        ticks, names = [], []
        k = int(lo / step) + (1 if lo % step > 1e-9 else 0)
        while True:
            x = k * step
            if x > hi + 1e-9:
                break
            ticks.append(x)
            d = base + datetime.timedelta(days=x)
            if step >= 1:
                names.append(d.strftime("%d.%m.%y") if vspan > 350
                             else d.strftime("%d.%m"))
            else:
                names.append(d.strftime("%H:%M"))
            k += 1
        self.ax.set_xticks(ticks)
        self.ax.set_xticklabels(names, fontsize=7)

    # ---------------- зебра (фон периодов) ----------------
    def _shade_months(self, ax, lo, hi):
        """Зебра по месяцам: нечётные — закрашены, первое число — линия."""
        d = self._start + datetime.timedelta(days=int(lo))
        d = d.replace(day=1)
        y, m = d.year, d.month
        while True:
            d0 = datetime.date(y, m, 1)
            x0 = (d0 - self._start).days
            if x0 > hi:
                break
            ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
            d1 = datetime.date(ny, nm, 1)
            x1 = (d1 - self._start).days
            if (y * 12 + m) % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            y, m = ny, nm

    def _shade_weeks(self, ax, lo, hi):
        """Зебра по неделям (ISO): нечётные — закрашены, понедельник — линия."""
        d = self._start + datetime.timedelta(days=int(lo))
        d -= datetime.timedelta(days=d.weekday())
        while True:
            x0 = (d - self._start).days
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
        """Зебра по дням: нечётные — закрашены, полночь — линия."""
        d = self._start + datetime.timedelta(days=int(lo))
        while True:
            x0 = (d - self._start).days
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