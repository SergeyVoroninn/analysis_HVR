"""
yearmap.py — годовой heatmap плотности записей ЭКГ.

Свойства:
  athlete — id спортсмена; при смене данные перезагружаются из БД;
  year    — отображаемый год; при смене перерисовываются ячейки;
  week    — индекс выбранной недели (0..52); при смене рисуется курсор.
Растягивается за окном: размер ячейки пересчитывается по ширине.
"""
import datetime
import time
import calendar
import tkinter as tk

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_TEXT_DIM, COL_WEEKDAY, COL_WEEKEND,
                   COL_FUTURE, COL_ONE, COL_MULTI, COL_WARN, COL_CRIT,
                   COL_SELECTION)

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]

X0, Y0 = 5, 18


class YearHeatmap(tk.Canvas):
    """Сетка 53 недели × 7 дней + подписи месяцев + курсор недели."""

    def __init__(self, master, db_path=None, cell=14, year=None,
                 on_week_pick=None):
        self._cell = cell
        self._step = cell + 1
        super().__init__(master, bg=COL_BG_DARK, highlightthickness=0,
                         width=53 * self._step + 10,
                         height=Y0 + 7 * self._step + 6)

        self.db_path = db_path or get_db_path()
        self.on_week_pick = on_week_pick     # callback(week, week_start_date)

        self._athlete_id = None
        self._year = year or datetime.date.today().year
        self._week = None
        self._date_map = {}
        self._year_start = None

        self._cells, self._colors, self._month_labels = [], [], []
        self._rebuild_grid()
        self._recalc_year()
        self._redraw_cells()

        self.on_year_change = None        # callback(delta)
        self.on_year_zoom = None         # callback(start_date, end_date) при ПКМ на год
        self.on_month_zoom = None        # callback(start_date, end_date)
        self._wheel_lock = 0.0            # блокировка длинного жеста колеса
        self._click_t = 0.0
        self._click_w = -1
        self._single_timer = None
        self._load_seq = 0
        self.on_week_dbl = None           # callback(week, monday) — двойной клик

        self.bind("<Button-1>", self._on_click)
        self.bind("<Button-3>", self._on_right_click)  # НОВОЕ: ПКМ для зума на месяц
        self.bind("<MouseWheel>", self._on_wheel)
        self._y_shift = None

    # ================= свойства =================
    @property
    def athlete(self):
        return self._athlete_id

    @athlete.setter
    def athlete(self, aid):
        if aid == self._athlete_id:
            return
        self._athlete_id = aid
        self._load_data()
        self._redraw_cells()

    @property
    def year(self):
        return self._year

    @year.setter
    def year(self, y):
        if y == self._year:
            return
        self._year = y
        self._recalc_year()
        self._redraw_cells()
        self._redraw_cursor()

    @property
    def week(self):
        return self._week

    @week.setter
    def week(self, w):
        self._week = w if (0 <= w < 53) else None
        self._redraw_cursor()

    def week_start_date(self, w=None):
        """Понедельник выбранной (или заданной) недели."""
        w = self._week if w is None else w
        if w is None or self._year_start is None:
            return None
        return self._year_start + datetime.timedelta(weeks=w)

    def set_cursor_by_date(self, d):
        """Установить курсор и год по календарной дате d."""
        self._year = d.year
        self._recalc_year()
        self._redraw_cells()
        w = (d - self._year_start).days // 7
        self._week = w if 0 <= w < 53 else None
        self._redraw_cursor()
        return self._week                    # чтобы синхронизировать weekmap

    # ================= данные из БД =================
    def _load_data(self):
        self._date_map = {}
        if self._athlete_id is None:
            self._redraw_cells()
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
        self._date_map = {}
        for recorded_at, status in rows:
            dkey = datetime.datetime.fromisoformat(recorded_at).date().isoformat()
            m = self._date_map.setdefault(dkey, {"count": 0, "worst": None})
            m["count"] += 1
            if status == "crit":
                m["worst"] = "crit"
            elif status == "warn" and m["worst"] != "crit":
                m["worst"] = "warn"
        self._redraw_cells()

    # ================= ресайз =================
    def height_for_step(self, step):
        """Высота канваса при шаге ячейки step (cell + 1)."""
        return Y0 + 7 * step + 6

    def set_cell(self, cell):
        """Задать размер ячейки извне (приложение само считает по ширине)."""
        import os
        if os.environ.get("HVR_DEBUG") == "1":
            print(f"[yearmap] set_cell {cell}", flush=True)
        cell = int(max(6, min(cell, 22)))
        if cell == self._cell:
            return
        self._cell = cell
        self._step = cell + 1
        self._rebuild_grid()
        self._recalc_year()
        self._redraw_cells()
        self._redraw_cursor()

    # ================= построение =================
    def _rebuild_grid(self):
        self.delete("all")
        self._cells, self._colors, self._month_labels = [], [], []
        s, c = self._step, self._cell
        self.config(width=53 * s + 10, height=Y0 + 7 * s + 6)
        for w in range(53):
            for d in range(7):
                x, y = X0 + w * s, Y0 + d * s
                cid = self.create_rectangle(x, y, x + c, y + c,
                                            fill=COL_BG_DARK, outline='')
                self._cells.append(cid)
                self._colors.append(None)
        for m in range(12):
            tid = self.create_text(-100, 8, text=MONTHS_RU[m], fill=COL_TEXT_DIM,
                                   anchor='w', font=('Segoe UI', 9))
            self._month_labels.append(tid)

    def _recalc_year(self):
        jan1 = datetime.date(self._year, 1, 1)
        self._year_start = jan1 - datetime.timedelta(days=jan1.weekday())
        for m in range(12):
            w = (datetime.date(self._year, m + 1, 1) - self._year_start).days // 7
            if 0 <= w < 53:
                self.coords(self._month_labels[m], X0 + w * self._step, 8)
            else:
                self.coords(self._month_labels[m], -100, 8)

    # ================= отрисовка =================
    def _cell_color(self, count, worst, base):
        if worst == 'crit':
            return COL_CRIT
        if worst == 'warn':
            return COL_WARN
        if count >= 2:
            return COL_MULTI
        if count == 1:
            return COL_ONE
        return base

    def _redraw_cells(self):
        today = datetime.date.today()
        jan1 = datetime.date(self._year, 1, 1)
        dec31 = datetime.date(self._year, 12, 31)

        idx = 0
        for w in range(53):
            for d in range(7):
                day = self._year_start + datetime.timedelta(weeks=w, days=d)
                if day > today or day < jan1 or day > dec31:
                    color = COL_FUTURE
                else:
                    base = COL_WEEKEND if d >= 5 else COL_WEEKDAY
                    info = self._date_map.get(day.isoformat())
                    color = self._cell_color(info["count"], info["worst"],
                                             base) if info else base
                if self._colors[idx] != color:
                    self.itemconfigure(self._cells[idx], fill=color)
                    self._colors[idx] = color
                idx += 1

    def _redraw_cursor(self):
        self.delete('sel')
        if self._week is None:
            return
        s, c = self._step, self._cell
        x = X0 + self._week * s
        self.create_rectangle(x - 1, Y0 - 1, x + c + 1, Y0 + 7 * s,
                              outline=COL_SELECTION, width=2, tags='sel')

    # ================= события =================
    def _on_click(self, event):
        w = (event.x - X0) // self._step
        if not (0 <= w < 53):
            return
        now = time.monotonic()
        is_dbl = (now - self._click_t < 0.45 and w == self._click_w)
        self._click_t = now
        self._click_w = w

        if is_dbl:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
                self._single_timer = None
            self.week = w
            monday = self.week_start_date(w)
            if self.on_week_dbl:
                self.on_week_dbl(w, monday)
            return

        self.week = w
        if self.on_week_pick:
            monday = self.week_start_date(w)
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
            self._single_timer = self.after(
                300, lambda mm=monday: self._fire_week_pick(mm))

    def _fire_week_pick(self, monday):
        self._single_timer = None
        if self.on_week_pick:
            w = self.week
            self.on_week_pick(w, monday)

    def _on_right_click(self, event):
        """ПКМ на любой ячейке heatmap устанавливает диапазон года на графиках."""
        w = (event.x - X0) // self._step
        if not (0 <= w < 53):
            return

        clicked_date = self._year_start + datetime.timedelta(weeks=w, days=3)  # середина недели
        year = clicked_date.year
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)

        if self.on_year_zoom:
            self.on_year_zoom(start_date, end_date)

    def _on_wheel(self, event):
        """Колесо над yearmap: переключение года."""
        now = time.monotonic()
        if now < self._wheel_lock:
            return                          # игнорируем повторные срабатывания
        
        # 0.2 секунды (200 мс) — идеально: гасит двойные срабатывания мыши, 
        # но не создает ощущения задержки ("как только колесо останавливалось")
        self._wheel_lock = now + 0.2
        
        # Кроссплатформенное определение направления прокрутки
        if hasattr(event, 'delta'):
            delta = 1 if event.delta > 0 else -1
        elif hasattr(event, 'num'):
            delta = 1 if event.num == 4 else -1  # Linux
        else:
            return

        if self.on_year_change:
            self.on_year_change(delta)
        else:
            self.year += delta