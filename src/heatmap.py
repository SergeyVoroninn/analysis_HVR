"""
heatmap.py — составной виджет: переключатель года сверху,
годовой heatmap слева, недельный справа.

При ресайзе окна вместо пересборки сеток рисуются белые «призрачные»
рамки; сетки пересобираются один раз после окончания ресайза.
"""
import tkinter as tk

from theme import COL_BG_DARK, COL_TEXT_LIGHT
from yearmap import YearHeatmap
from weekmap import WeekHeatmap


class Heatmap(tk.Frame):
    """Единая панель плотности записей ЭКГ."""

    def __init__(self, master, db_path=None, on_week_pick=None, on_pick=None):
        super().__init__(master, bg=COL_BG_DARK)

        # ---------- переключатель года ----------
        ctrl = tk.Frame(self, bg=COL_BG_DARK)
        ctrl.grid(row=0, column=0, pady=5)
        tk.Button(ctrl, text="◀",
                  command=lambda: self._change_year(-1)).pack(side="left")
        self._lbl_year = tk.Label(ctrl, text="", bg=COL_BG_DARK,
                                  fg=COL_TEXT_LIGHT,
                                  font=("Segoe UI", 12, "bold"))
        self._lbl_year.pack(side="left", padx=6)
        tk.Button(ctrl, text="▶",
                  command=lambda: self._change_year(1)).pack(side="left")

        # ---------- heatmap'ы ----------
        self._maps = tk.Frame(self, bg=COL_BG_DARK)
        self._maps.grid(row=1, column=0, sticky="new")
        self.year_map = YearHeatmap(self._maps, db_path=db_path)
        self.year_map.pack(side="left")
        self.week_map = WeekHeatmap(self._maps, db_path=db_path, on_pick=on_pick)
        self.week_map.pack(side="left", padx=(20, 0))

        # ---------- оверлей с «призрачными» рамками ----------
        # лежит в той же ячейке grid, что и maps; когда виден — закрывает сетки
        self._overlay = tk.Canvas(self, bg=COL_BG_DARK, highlightthickness=0)
        self._overlay.grid(row=1, column=0, sticky="nw")
        self._overlay.grid_remove()

        self._cur_t = None            # текущий применённый step
        self._finalize_timer = None

        self._on_week_pick = on_week_pick
        self.year_map.on_week_pick = self._sync_week

        self._lbl_year.configure(text=str(self.year))
        self.bind("<Configure>", self._on_resize)

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

    # ---------------- ресайз: ghost-рамки до отпускания мыши ----------------
    def _on_resize(self, event):
        avail = self.winfo_width()
        if avail < 100:
            return
        t = int(max(7, min((avail - 60) // 60, 23)))

        if self._cur_t is None:                      # первый замер
            self._apply_resize(t)
            return
        if t == self._cur_t and self._finalize_timer is None:
            return

        if not self._mouse_held():
            # мышь НЕ зажата: максимизация / финальный «settle» после отпускания —
            # применяем сразу, без призрака и без повторной вспышки
            self._apply_resize(t)
            return

        # мышь зажата: белые рамки до отпускания
        self._overlay.grid()
        yw, yh = 53 * t + 10, 24 + 7 * t
        ww, wh = 24 + 7 * t + 6, 30 + 8 * t
        self._overlay.configure(width=yw + 20 + ww + 2,
                                height=max(yh, wh) + 2)
        self._overlay.delete("ghost")
        self._overlay.create_rectangle(1, 1, yw, yh, outline="white", tags="ghost")
        self._overlay.create_rectangle(yw + 21, 1, yw + 20 + ww, wh,
                                       outline="white", tags="ghost")

        if self._finalize_timer:
            self.after_cancel(self._finalize_timer)
        self._finalize_timer = self.after(100, self._apply_resize, t)

    def _apply_resize(self, t):
        self._finalize_timer = None
        if self._mouse_held():
            # всё ещё тянут окно — ждём отпускания
            self._finalize_timer = self.after(100, self._apply_resize, t)
            return
        self._cur_t = t
        self.year_map.set_cell(t - 1)
        self.week_map.set_cell(t - 1)
        self._overlay.delete("ghost")
        self._overlay.grid_remove()

    @staticmethod
    def _mouse_held():
        """Зажата ли левая кнопка мыши прямо сейчас (Windows)."""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False      # не-Windows — фиксируем сразу