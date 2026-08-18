"""
charts.py — готовые параметры и общий контейнер графиков.
Отрисовка одного графика — в metricplot.py, ghost-ресайз — в ghost.py.
"""
import tkinter as tk

from analysis import stress_level
from theme import COL_ONE, COL_WARN, COL_CRIT, COL_HIGH
from metricplot import MetricPlot, MetricSpec
from ghost import GhostResizeFrame


def _si_color(v):
    return {"низкий": COL_ONE, "умеренный": COL_WARN,
            "высокий": COL_HIGH, "перенапряжение": COL_CRIT}.get(
        stress_level(v), COL_ONE)


TP_METRIC = MetricSpec("tp", "TP", "мс²",
                       lambda r: r.sdnn * r.sdnn if r.sdnn is not None else None)
SI_METRIC = MetricSpec("si", "Стресс", "ИС",
                       lambda r: r.stress_si, _si_color)


class ChartsPanel(GhostResizeFrame):
    """Общий контейнер графиков: высота каждого = ширина / ASPECT."""

    ASPECT = 6

    def __init__(self, master, metrics, db_path=None):
        super().__init__(master)
        self._plots = [MetricPlot(self, m, db_path=db_path) for m in metrics]
        for p in self._plots:
            p.pack(side="top", fill="x", pady=2)

    # ---------------- хуки ghost-ресайза ----------------
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