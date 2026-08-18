"""
heatmap.py — составной виджет: переключатель года сверху,
годовой heatmap слева, недельный справа.

Размер задаётся извне через ResizeController (ghost.py): методы
target_size / ghost_rects / apply_size. Сам виджет на <Configure> не
реагирует — никакой обратной связи с раскладкой.
"""
import datetime
import tkinter as tk

from theme import COL_BG_DARK, COL_TEXT_LIGHT
from yearmap import YearHeatmap
from weekmap import WeekHeatmap
from database import get_db_path
from models import get_session, ECGRecord


class Heatmap(tk.Frame):
    """Единая панель плотности записей ЭКГ."""

    def __init__(self, master, db_path=None, on_week_pick=None, on_week_dbl_pick=None, on_pick=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.db_path = db_path or get_db_path()

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

        self._on_week_pick = on_week_pick           # одинарный клик
        self._on_week_dbl_pick = on_week_dbl_pick   # двойной клик
        self.year_map.on_week_pick = self._sync_week
        self.year_map.on_year_change = self._change_year
        self.year_map.on_week_dbl = self._zoom_to_week
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

    def _zoom_to_week(self, w, monday):
        """Двойной клик по yearmap — диапазон графика = кликнутая неделя."""
        if monday is None:
            return
        self.week_map.week_start = monday
        if self._on_week_dbl_pick:
            self._on_week_dbl_pick(w, monday)

    def set_selection(self, year=None, week=None):
        """Восстановление состояния: год и курсор недели (+ недельная карта)."""
        if year is not None:
            self.year = year
        if week is not None:
            self.week = week
            d = self.year_map.week_start_date(week)
            if d:
                self.week_map.week_start = d

    def set_year(self, year):
        """Переключить год и поставить курсор в середину года (~26-я неделя)."""
        self.year = year
        self.week = 26
        d = self.year_map.week_start_date(26)
        if d:
            self.week_map.week_start = d

    def set_cursor_by_date(self, d):
        """Поставить курсор на неделю, содержащую дату d."""
        w = self.year_map.set_cursor_by_date(d)
        self._lbl_year.configure(text=str(self.year_map.year))
        if w is not None:
            self.week_map.week_start = self.year_map.week_start_date(w)

    def reset_to_data_center(self):
        """Сброс yearmap на середину диапазона данных атлета."""
        session = get_session(self.db_path)
        try:
            row = (session.query(ECGRecord.recorded_at)
                   .filter(ECGRecord.athlete_id == self.year_map.athlete)
                   .order_by(ECGRecord.recorded_at.asc()).first())
            if not row or not row[0]:
                return
            first = datetime.datetime.fromisoformat(row[0]).date()
            row = (session.query(ECGRecord.recorded_at)
                   .filter(ECGRecord.athlete_id == self.year_map.athlete)
                   .order_by(ECGRecord.recorded_at.desc()).first())
            last = datetime.datetime.fromisoformat(row[0]).date()
        finally:
            session.close()

        mid = first + (last - first) / 2
        self.year = mid.year
        w = mid.isocalendar()[1] - 1
        self.week = max(0, min(52, w))
        d = self.year_map.week_start_date(self.week)
        if d:
            self.week_map.week_start = d

    def _ctrl_req(self):
        """Высота панели переключателя года: дети + pady 5 сверху и снизу."""
        hs = [c.winfo_reqheight() for c in self._ctrl.winfo_children()]
        return (max(hs) if hs else 1) + 10

    # ---------------- хуки ghost-ресайза ----------------
    def ghost_shown(self):
        pass

    def ghost_hidden(self):
        pass

    def target_size(self, avail_w):
        """Ширина: 60*t+60; высота: переключатель + максимум из двух карт."""
        t = int(max(7, min((avail_w - 60) // 60, 23)))   # step = cell + 1
        self._pending_t = t
        w = 60 * t + 60
        ctrl_h = self._ctrl_req()
        maps_h = max(self.year_map.height_for_step(t),
                     self.week_map.height_for_step(t))
        return w, ctrl_h + maps_h

    def ghost_rects(self, w, h):
        t = self._pending_t
        y0 = self._ctrl_req()
        yw = 53 * t + 10
        yh = self.year_map.height_for_step(t)
        ww = 24 + 7 * t + 6
        wh = self.week_map.height_for_step(t)
        return [(1, y0, yw, y0 + yh),
                (yw + 21, y0, yw + 20 + ww, y0 + wh)]

    def apply_size(self, w, h):
        if self._pending_t is None:
            return
        self.year_map.set_cell(self._pending_t - 1)
        self.week_map.set_cell(self._pending_t - 1)