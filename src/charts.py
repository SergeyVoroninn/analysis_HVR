"""
charts.py — готовые параметры и общий контейнер графиков.

Отрисовка одного графика — в metricplot.py.
"""
import tkinter as tk

from analysis import stress_level
from theme import COL_BG_DARK, COL_ONE, COL_WARN, COL_CRIT
from metricplot import MetricPlot, MetricSpec

COL_HIGH = "#ff8c42"


def _si_color(v):
    return {"низкий": COL_ONE, "умеренный": COL_WARN,
            "высокий": COL_HIGH, "перенапряжение": COL_CRIT}.get(
        stress_level(v), COL_TEXT_DIM)


TP_METRIC = MetricSpec("tp", "TP", "мс²",
                       lambda r: r.sdnn * r.sdnn if r.sdnn is not None else None)
SI_METRIC = MetricSpec("si", "Стресс", "ИС",
                       lambda r: r.stress_si, _si_color)


class ChartsPanel(tk.Frame):
    """Общий контейнер: стопка графиков по списку метрик.

    ASPECT — высота каждого графика = ширина / ASPECT.
    """
    ASPECT = 6

    def __init__(self, master, metrics, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self._plots = [MetricPlot(self, m, db_path=db_path) for m in metrics]
        for p in self._plots:
            p.pack(side="top", fill="x", pady=2)

        self._size_timer = None
        self.bind("<Configure>", self._on_resize)
        self.master.bind("<Configure>", self._on_resize, add="+")
        self.after(150, self._apply_size)

    def _on_resize(self, event=None):
        if self._size_timer:
            self.after_cancel(self._size_timer)
        self._size_timer = self.after(30, self._apply_size)

    def _apply_size(self):
        self._size_timer = None
        self.update_idletasks()
        for p in self._plots:
            w = p.widget.winfo_width()
            if w < 50:
                continue
            p.set_size(w, max(120, int(w / self.ASPECT)))

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