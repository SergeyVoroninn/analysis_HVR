"""
charts.py — готовые параметры и общий контейнер графиков.
Отрисовка одного графика — в metricplot.py. Размер задаётся извне через
ResizeController (ghost.py): target_size / ghost_rects / apply_size.
"""
import tkinter as tk

from analysis import stress_level
from theme import COL_BG_DARK, COL_ONE, COL_WARN, COL_CRIT, COL_HIGH
from metricplot import MetricPlot, MetricSpec


def _si_color(v):
    return {"низкий": COL_ONE, "умеренный": COL_WARN,
            "высокий": COL_HIGH, "перенапряжение": COL_CRIT}.get(
        stress_level(v), COL_ONE)


TP_METRIC = MetricSpec("tp", "TP", "мс²",
                       lambda r: r.sdnn * r.sdnn if r.sdnn is not None else None)
SI_METRIC = MetricSpec("si", "Стресс", "ИС",
                       lambda r: r.stress_si, _si_color)


class ChartsPanel(tk.Frame):
    """Общий контейнер графиков: высота каждого = ширина / ASPECT."""

    ASPECT = 6

    def __init__(self, master, metrics, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self._plots = [MetricPlot(self, m, db_path=db_path) for m in metrics]
        for p in self._plots:
            p.on_view_changed = self._apply_zoom
            p.pack(side="top", fill="x", pady=2)

    def _apply_zoom(self, view):
        """Единый масштаб на все графики."""
        for p in self._plots:
            p.view = view
        for p in self._plots:
            p.redraw()

    def set_year_pick_callback(self, cb):
        for p in self._plots:
            p.on_year_pick = cb

    def set_reset_callback(self, cb):
        for p in self._plots:
            p.on_reset = cb

    def set_single_click_callback(self, cb):
        for p in self._plots:
            p.on_single_click = cb

    # ---------------- хуки ghost-ресайза ----------------
    def ghost_shown(self):
        for p in self._plots:
            p.set_frozen(True)

    def ghost_hidden(self):
        for p in self._plots:
            p.set_frozen(False)

    def target_size(self, avail_w):
        h_each = max(120, int(avail_w / self.ASPECT))
        return avail_w, len(self._plots) * (h_each + 4)

    def ghost_rects(self, w, h):
        h_each = max(120, int(w / self.ASPECT))
        rects, y = [], 0
        for _ in self._plots:
            rects.append((1, y + 1, w - 1, y + h_each))
            y += h_each + 4
        return rects

    def apply_size(self, w, h):
        h_each = max(120, int(w / self.ASPECT))
        for p in self._plots:
            p.set_size(w, h_each)

    # ---------------- входы ----------------
    @property
    def athlete(self):
        return self._plots[0].athlete if self._plots else None

    @athlete.setter
    def athlete(self, aid):
        for p in self._plots:
            p.athlete = aid

    def set_range(self, start, end):
        for p in self._plots:
            p.set_range(start, end)

    # ---------------- общий масштаб по X ----------------
    @property
    def zoom(self):
        """Абсолютное окно (lo, hi) в ординалах или None."""
        return self._plots[0].view if self._plots else None

    @zoom.setter
    def zoom(self, view):
        for p in self._plots:
            p.view = view

    def redraw(self):
        for p in self._plots:
            p.redraw()

    def center_on_week(self, week_start_date):
        """Центрировать графики по среде выбранной недели."""
        if self._plots:
            self._plots[0].center_on_week(week_start_date)

    def zoom_to_week(self, week_start_date):
        """Диапазон графиков = кликнутая неделя (пн–вс)."""
        if not self._plots:
            return
        p0 = self._plots[0]
        if p0._start is None:
            return
        import datetime as _dt
        monday = week_start_date
        sunday = monday + _dt.timedelta(days=6)
        lo = p0._ord(monday)
        hi = p0._ord(sunday) + 1
        p0._commit_view(lo, hi)
