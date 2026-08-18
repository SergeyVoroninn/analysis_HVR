"""
heatmap.py — составной виджет: переключатель года сверху,
годовой heatmap слева, недельный справа.

Ресайз — через базовый класс GhostResizeFrame: во время перетаскивания
показываются белые рамки, пересборка — при отпускании мыши.
"""
import tkinter as tk

from theme import COL_BG_DARK, COL_TEXT_LIGHT
from ghost import GhostResizeFrame
from yearmap import YearHeatmap
from weekmap import WeekHeatmap


class Heatmap(GhostResizeFrame):
    """Единая панель плотности записей ЭКГ."""

    def __init__(self, master, db_path=None, on_week_pick=None, on_pick=None):
        super().__init__(master)

        # ---------- переключатель года ----------
        self._ctrl = tk.Frame(self, bg=COL_BG_DARK)
        self._ctrl.pack(side="top", pady=5)
        tk.Button(self._ctrl, text="◀",
                  command=lambda: self._change_year(-1)).pack(side="left")
        self._lbl_year = tk.Label(self._ctrl, text="", bg=COL_BG_DARK,
                                  fg=COL_TEXT_LIGHT,
                                  font=("Segoe UI", 12, "bold"))
        self._lbl_year.pack(side="left", padx=6)
        tk.Button(self._ctrl, text="▶",
                  command=lambda: self._change_year(1)).pack(side="left")

        # ---------- heatmap'ы ----------
        self._maps = tk.Frame(self, bg=COL_BG_DARK)
        self._maps.pack(side="top")
        self.year_map = YearHeatmap(self._maps, db_path=db_path)
        self.year_map.pack(side="left")
        self.week_map = WeekHeatmap(self._maps, db_path=db_path, on_pick=on_pick)
        self.week_map.pack(side="left", padx=(20, 0))

        self._on_week_pick = on_week_pick
        self.year_map.on_week_pick = self._sync_week
        self._pending_t = None

        self._lbl_year.configure(text=str(self.year))

    # ---------------- сквозные свойства ----------------
    @property
    def athlete(self):
        return self.year_map.athlete

    @athlete.setter
    def athlete(self, aid):
        self.year_map.athlete = aid
        self.week_map.athlete = aid

    @property
    def year(self):
        return self.year_map.year

    @year.setter
    def year(self, y):
        self.year_map.year = y
        self._lbl_year.configure(text=str(y))

    @property
    def week(self):
        return self.year_map.week

    @week.setter
    def week(self, w):
        self.year_map.week = w

    # ---------------- внутреннее ----------------
    def _change_year(self, delta):
        self.year += delta

    def _sync_week(self, w, d):
        self.week_map.week_start = d
        if self._on_week_pick:
            self._on_week_pick(w, d)

    def _ctrl_h(self):
        return max(1, self._ctrl.winfo_height())

    # ---------------- хуки ghost-ресайза ----------------
    def target_size(self, avail_w):
        """Общая ширина: (53*t+10) + 20 + (24+7*t+6) = 60*t+60."""
        t = int(max(7, min((avail_w - 60) // 60, 23)))   # step = cell + 1
        self._pending_t = t
        w = 60 * t + 60
        h = self._ctrl_h() + max(24 + 7 * t, 30 + 8 * t)
        return w, h

    def ghost_rects(self, w, h):
        t = self._pending_t
        y0 = self._ctrl_h()
        yw, yh = 53 * t + 10, 24 + 7 * t
        ww, wh = 24 + 7 * t + 6, 30 + 8 * t
        return [(1, y0, yw, y0 + yh),
                (yw + 21, y0, yw + 20 + ww, y0 + wh)]

    def apply_size(self, w, h):
        if self._pending_t is None:
            return
        self.year_map.set_cell(self._pending_t - 1)
        self.week_map.set_cell(self._pending_t - 1)