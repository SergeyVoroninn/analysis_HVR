"""
weekmap.py — недельный heatmap: 7 дней × 8 блоков.
Логика кликов полностью синхронизирована с yearmap.py для надежности.
"""
import datetime
import time as _time
import tkinter as tk

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_TEXT_DIM, COL_WEEKDAY, COL_WEEKEND,
                   COL_FUTURE, COL_ONE, COL_MULTI, COL_WARN, COL_CRIT)

X0, Y0 = 24, 4


class WeekHeatmap(tk.Frame):
    def __init__(self, master, db_path=None, cell=14, on_pick=None):
        super().__init__(master, bg=COL_BG_DARK)
        self._cell = cell
        self._step = cell + 1

        self._title = tk.Label(self, text="—", bg=COL_BG_DARK, fg=COL_TEXT_DIM,
                               font=("Segoe UI", 10))
        self._title.pack(anchor="w")

        self._cnv = tk.Canvas(self, bg=COL_BG_DARK, highlightthickness=0)
        self._cnv.pack()

        self.db_path = db_path or get_db_path()
        self.on_pick = on_pick
        
        self.on_day_dbl = None
        self.on_week_rmb = None

        self._athlete_id = None
        self._week_start = None
        self._block_map = {}
        self._load_seq = 0
        
        # Отслеживаем время и ИНДЕКС ЯЧЕЙКИ, а не пиксели (как в yearmap.py)
        self._click_t = 0.0
        self._click_d = -1
        self._click_b = -1
        self._single_timer = None

        self._cells, self._colors = {}, {}
        self._rebuild_grid()
        self._redraw()

        # ТОЛЬКО одинарный клик и ПКМ. Двойной клик детектируется внутри _on_click
        self._cnv.bind("<Button-1>", self._on_click)
        self._cnv.bind("<Button-3>", self._on_week_rmb_click)

    @property
    def athlete(self):
        return self._athlete_id

    @athlete.setter
    def athlete(self, aid):
        if aid == self._athlete_id:
            return
        self._athlete_id = aid
        self._load_data()
        self._redraw()

    @property
    def week_start(self):
        return self._week_start

    @week_start.setter
    def week_start(self, d):
        if d == self._week_start:
            return
        self._week_start = d
        self._redraw()

    def set_cell(self, cell):
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[weekmap] set_cell {cell}", flush=True)
        cell = int(max(6, min(cell, 22)))
        if cell == self._cell:
            return
        self._cell = cell
        self._step = cell + 1
        self._rebuild_grid()
        self._redraw()

    def height_for_step(self, step):
        return self._title.winfo_reqheight() + Y0 + 8 * step + 6

    def _load_data(self):
        self._block_map = {}
        if self._athlete_id is None:
            self._redraw()
            return

        self._load_seq += 1
        seq = self._load_seq
        athlete = self._athlete_id

        def worker():
            try:
                rows = self._fetch_rows(athlete)
            except Exception:
                rows = []
            self.after(0, lambda: self._apply_loaded(seq, athlete, rows))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _fetch_rows(self, athlete):
        session = get_session(self.db_path)
        try:
            return (session.query(ECGRecord.recorded_at, ECGRecord.status)
                    .filter(ECGRecord.athlete_id == athlete).all())
        finally:
            session.close()

    def _apply_loaded(self, seq, athlete, rows):
        if seq != self._load_seq or athlete != self._athlete_id:
            return
        self._block_map = {}
        for recorded_at, status in rows:
            dt = datetime.datetime.fromisoformat(recorded_at)
            key = (dt.date().isoformat(), dt.hour // 3)
            m = self._block_map.setdefault(key, {"count": 0, "worst": None})
            m["count"] += 1
            if status == "crit":
                m["worst"] = "crit"
            elif status == "warn" and m["worst"] != "crit":
                m["worst"] = "warn"
        self._redraw()

    def _rebuild_grid(self):
        self._cnv.delete("all")
        self._cells, self._colors = {}, {}
        s, c = self._step, self._cell
        self._cnv.config(width=X0 + 7 * s + 6, height=Y0 + 8 * s + 6)

        for b in range(8):
            self._cnv.create_text(X0 - 4, Y0 + b * s + c // 2,
                                  text=f"{b * 3:02d}", fill=COL_TEXT_DIM,
                                  anchor='e', font=('Segoe UI', 9))
        for d in range(7):
            for b in range(8):
                x, y = X0 + d * s, Y0 + b * s
                cid = self._cnv.create_rectangle(x, y, x + c, y + c,
                                                 fill=COL_BG_DARK, outline='')
                self._cells[(d, b)] = cid
                self._colors[(d, b)] = None

    def _cell_color(self, count, worst, base):
        if worst == 'crit': return COL_CRIT
        if worst == 'warn': return COL_WARN
        if count >= 2: return COL_MULTI
        if count == 1: return COL_ONE
        return base

    def _redraw(self):
        if self._week_start is None:
            self._title.configure(text="—")
            return
        ws = self._week_start
        we = ws + datetime.timedelta(days=6)
        self._title.configure(text=f"Неделя {ws:%d.%m}–{we:%d.%m}")

        today = datetime.date.today()
        for d in range(7):
            day = ws + datetime.timedelta(days=d)
            for b in range(8):
                if day > today:
                    color = COL_FUTURE
                else:
                    base = COL_WEEKEND if d >= 5 else COL_WEEKDAY
                    info = self._block_map.get((day.isoformat(), b))
                    color = self._cell_color(info["count"], info["worst"], base) if info else base
                if self._colors[(d, b)] != color:
                    self._cnv.itemconfigure(self._cells[(d, b)], fill=color)
                    self._colors[(d, b)] = color

    # ================= СОБЫТИЯ (КАК В YEARMAP.PY) =================
    def _on_click(self, event):
        d = (event.x - X0) // self._step
        b = (event.y - Y0) // self._step
        if not (0 <= d < 7 and 0 <= b < 8) or self._week_start is None:
            return

        now = _time.monotonic()
        # Проверяем время И совпадение индекса ячейки. Это намного надежнее проверки пикселей!
        is_dbl = (now - self._click_t < 0.45 and d == self._click_d and b == self._click_b)
        
        self._click_t = now
        self._click_d = d
        self._click_b = b

        if is_dbl:
            # Двойной клик: отменяем таймер одинарного и вызываем колбэк
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
                self._single_timer = None
            
            day = self._week_start + datetime.timedelta(days=d)
            if self.on_day_dbl:
                self.on_day_dbl(day, day + datetime.timedelta(days=1))
            return  # ВАЖНО: выходим, чтобы не запланировать одинарный клик

        # Одинарный клик: планируем выполнение
        day = self._week_start + datetime.timedelta(days=d)
        block = b if (day.isoformat(), b) in self._block_map else None
        
        if self.on_pick:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
            self._single_timer = self.after(
                350, lambda dd=day, bb=block: self._fire_single(dd, bb))

    def _fire_single(self, day, block):
        self._single_timer = None
        if self.on_pick:
            self.on_pick(day, block)

    def _on_week_rmb_click(self, event):
        """ПКМ по weekmap: устанавливаем диапазон на всю отображаемую неделю."""
        if self._week_start is None:
            return
        
        week_start = self._week_start
        week_end = week_start + datetime.timedelta(days=7)
        
        if self.on_week_rmb:
            self.on_week_rmb(week_start, week_end)