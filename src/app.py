"""
Приложение для просмотра базы данных ЭКГ (одна страница, без вкладки ЭКГ).
"""
import sqlite3
import uuid
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
import tkinter as tk
import datetime

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)

from analysis import parse_rr, calc_metrics, calc_stress, stress_level
from athlete_generator import (
    _generate_polar_id, _estimate_height_cm, _estimate_weight_kg,
    _estimate_resting_hr, _estimate_max_hr, _estimate_hrv_rmssd)
from database import get_connection, get_db_path


# ============================================================
# ЦВЕТА ИНТЕРФЕЙСА
# ============================================================
COL_BG_DARK = '#2b2b2b'
COL_BG_WIDGET = '#2b2b2b'
COL_TEXT_LIGHT = '#cccccc'
COL_TEXT_DIM = '#9a9a9a'
COL_SPINE = '#555555'
COL_SELECTION = 'white'

COL_WEEKDAY = '#4a4a4a'
COL_WEEKEND = '#333333'
COL_FUTURE = '#242424'

COL_ONE = "#45a056"
COL_MULTI = "#04811b"
COL_WARN = '#d29922'
COL_CRIT = '#da3633'

COL_TP_YEAR = '#4cc9f0'
COL_TP_WEEK = "#468056"

YEAR_X0, YEAR_Y0 = 5, 18
WEEK_X0, WEEK_Y0 = 28, 5

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

CTK_COLS = ["id", "last_name", "first_name", "middle_name", "gender",
            "birth_year", "age", "height_cm", "weight_kg", "resting_hr",
            "max_hr", "hrv_rmssd_baseline", "avg_rr_ms", "polar_id"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AthleteDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, data=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x440")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        fields = [("last_name", "Фамилия"), ("first_name", "Имя"),
                  ("middle_name", "Отчество"), ("birth_year", "Год рождения"),
                  ("height_cm", "Рост (см)"), ("weight_kg", "Вес (кг)"),
                  ("polar_id", "Polar ID")]
        self.entries = {}
        row = 0
        for key, label in fields:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, padx=12, pady=4, sticky="w")
            e = ctk.CTkEntry(self)
            e.grid(row=row, column=1, padx=12, pady=4, sticky="ew")
            self.entries[key] = e
            row += 1
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Пол").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        self.gender_var = ctk.StringVar(value="M")
        ctk.CTkOptionMenu(self, values=["M", "F"], variable=self.gender_var
                          ).grid(row=row, column=1, padx=12, pady=4, sticky="ew")
        row += 1

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=2, pady=12)
        ctk.CTkButton(btns, text="Сохранить", command=self._on_save).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Отмена", fg_color="gray",
                      command=self.destroy).pack(side="left", padx=6)

        if data:
            for key, _ in fields:
                if data.get(key) is not None:
                    self.entries[key].insert(0, str(data[key]))
            self.gender_var.set(data.get("gender", "M"))

    def _on_save(self):
        last = self.entries["last_name"].get().strip()
        first = self.entries["first_name"].get().strip()
        if not last or not first:
            messagebox.showwarning("Проверка", "Фамилия и имя обязательны.")
            return
        try:
            birth_year = int(self.entries["birth_year"].get().strip())
            if not 1900 <= birth_year <= datetime.date.today().year:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Проверка", "Некорректный год рождения.")
            return

        def opt_num(key, cast):
            v = self.entries[key].get().strip()
            if not v:
                return None
            try:
                return cast(v)
            except ValueError:
                return None

        self.result = {"last_name": last, "first_name": first,
                       "middle_name": self.entries["middle_name"].get().strip(),
                       "birth_year": birth_year, "gender": self.gender_var.get(),
                       "height_cm": opt_num("height_cm", int),
                       "weight_kg": opt_num("weight_kg", float),
                       "polar_id": self.entries["polar_id"].get().strip()}
        self.destroy()


class ECGViewerApp(ctk.CTk):
    def __init__(self, db_path=None):
        super().__init__()
        
        # Получаем путь к БД через менеджер
        if db_path is None:
            self.db_path = get_db_path()
        else:
            self.db_path = get_db_path(db_path)
        
        self.title("Просмотр ЭКГ — Анализ ВРС")
        self.geometry("1400x800")

        self.athletes = []
        self.selected_athlete = None

        self.cell = 14
        self.step = self.cell + 1

        self._day_block_map = {}
        self._year_start = None
        self._week_start = None
        self._selected_week = None
        self._view_year = datetime.date.today().year
        self._min_year = self._view_year
        self._max_year = self._view_year

        self._tp_last = None

        self._create_widgets()
        self._ensure_indexes()
        self._load_year_range()
        self._load_athletes()

    def _create_widgets(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, width=300)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.left_panel.grid_rowconfigure(1, weight=1)
        self.left_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.left_panel, text="Спортсмены",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, pady=10)

        self.tree_athletes = ttk.Treeview(
            self.left_panel, columns=("ФИО", "Возраст"), show="headings")
        self.tree_athletes.heading("ФИО", text="ФИО")
        self.tree_athletes.heading("Возраст", text="Возраст")
        self.tree_athletes.column("ФИО", width=200)
        self.tree_athletes.column("Возраст", width=60, anchor="center")
        self.tree_athletes.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_athletes.bind("<<TreeviewSelect>>", self._on_athlete_select)

        mgmt = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        mgmt.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(mgmt, text="＋", width=40, command=self._create_athlete
                      ).pack(side="left", padx=2, expand=True)
        ctk.CTkButton(mgmt, text="✎", width=40, command=self._edit_athlete
                      ).pack(side="left", padx=2, expand=True)
        ctk.CTkButton(mgmt, text="🗑", width=40, command=self._delete_athlete
                      ).pack(side="left", padx=2, expand=True)

        ctk.CTkButton(self.left_panel, text="⬇ Импорт записи ЭКГ",
                      command=self._import_ecg).grid(row=3, column=0, padx=5, pady=5, sticky="ew")

        self.right_panel = ctk.CTkFrame(self)
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(2, weight=1)

        self.frame_details = ctk.CTkFrame(self.right_panel)
        self.frame_details.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.label_details = ctk.CTkLabel(self.frame_details, text="Выберите спортсмена",
                                          font=ctk.CTkFont(size=14))
        self.label_details.pack(padx=10, pady=10)

        self.density_frame = ctk.CTkFrame(self.right_panel)
        self.density_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.density_frame.bind("<Configure>", self._on_density_resize)

        self.year_box = ctk.CTkFrame(self.density_frame, fg_color="transparent")
        self.year_box.pack(side="left", padx=10, pady=10)
        year_ctrl = ctk.CTkFrame(self.year_box, fg_color="transparent")
        year_ctrl.pack()
        ctk.CTkButton(year_ctrl, text="◀", width=28,
                      command=lambda: self._change_year(-1)).pack(side="left")
        self.label_year = ctk.CTkLabel(year_ctrl, text=str(self._view_year),
                                       font=ctk.CTkFont(size=14, weight="bold"))
        self.label_year.pack(side="left", padx=6)
        ctk.CTkButton(year_ctrl, text="▶", width=28,
                      command=lambda: self._change_year(1)).pack(side="left")

        self.canvas_year = tk.Canvas(self.year_box, bg=COL_BG_DARK, highlightthickness=0)
        self.canvas_year.pack()
        self.canvas_year.bind("<Button-1>", self._on_year_click)

        self.week_box = ctk.CTkFrame(self.density_frame, fg_color="transparent")
        self.week_box.pack(side="left", padx=20, pady=10)
        self.label_week_title = ctk.CTkLabel(self.week_box, text="Неделя",
                                             font=ctk.CTkFont(size=12))
        self.label_week_title.pack()
        self.canvas_week = tk.Canvas(self.week_box, bg=COL_BG_DARK, highlightthickness=0)
        self.canvas_week.pack()

        self.tp_frame = ctk.CTkFrame(self.right_panel)
        self.tp_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        self.tp_frame.grid_rowconfigure(1, weight=1)
        self.tp_frame.grid_columnconfigure(0, weight=1)
        self.label_tp = ctk.CTkLabel(self.tp_frame, text="TP (мс²) и индекс стресса (ИС)",
                                     font=ctk.CTkFont(size=12))
        self.label_tp.grid(row=0, column=0, padx=10, pady=(6, 0), sticky="w")

        self.plt_area = ctk.CTkFrame(self.tp_frame, fg_color="transparent")
        self.plt_area.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        self.fig_tp = Figure(figsize=(9, 4.6), dpi=100, constrained_layout=True)
        self.fig_tp.patch.set_facecolor(COL_BG_DARK)
        gs = self.fig_tp.add_gridspec(2, 2, width_ratios=[3, 1])
        self.ax_tp_year = self.fig_tp.add_subplot(gs[0, 0])
        self.ax_tp_week = self.fig_tp.add_subplot(gs[0, 1])
        self.ax_si_year = self.fig_tp.add_subplot(gs[1, 0])
        self.ax_si_week = self.fig_tp.add_subplot(gs[1, 1])

        self.canvas_tp = FigureCanvasTkAgg(self.fig_tp, master=self.plt_area)
        self._tp_widget = self.canvas_tp.get_tk_widget()
        self._tp_widget.configure(background=COL_BG_WIDGET)
        self._tp_widget.pack(fill="both", expand=True)

        self.plt_area.bind("<Configure>", self._on_tp_configure)

        self._apply_canvas_sizes()

    def _apply_canvas_sizes(self):
        s = self.step
        self.canvas_year.config(width=53 * s + 10, height=YEAR_Y0 + 7 * s + 6)
        self.canvas_week.config(width=WEEK_X0 + 7 * s + 6, height=WEEK_Y0 + 8 * s + 6)

    def _on_density_resize(self, event):
        avail = event.width
        if avail < 100:
            return
        week_block = WEEK_X0 + 7 * self.step + 40
        cell = (avail - week_block - 60) // 53
        cell = int(max(6, min(cell, 22)))
        if cell != self.cell:
            self.cell = cell
            self.step = cell + 1
            self._apply_canvas_sizes()
            if self.selected_athlete:
                self._draw_density(self.selected_athlete[0])

    def _on_tp_configure(self, event):
        w, h = event.width, event.height
        if w < 100 or h < 100 or self._tp_last == (w, h):
            return
        self._tp_last = (w, h)
        self.fig_tp.set_size_inches(w / self.fig_tp.dpi, h / self.fig_tp.dpi,
                                    forward=False)
        self.canvas_tp.draw_idle()

    def _get_athlete_full(self, aid):
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT " + ", ".join(CTK_COLS) + " FROM athletes WHERE id=?", (aid,))
        row = cur.fetchone()
        conn.close()
        return dict(zip(CTK_COLS, row)) if row else None

    def _create_athlete(self):
        dlg = AthleteDialog(self, "Новый спортсмен")
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        age = datetime.date.today().year - d["birth_year"]
        gender = d["gender"]
        height = d["height_cm"] or _estimate_height_cm(age, gender)
        weight = d["weight_kg"] or _estimate_weight_kg(height, age, gender)
        resting = _estimate_resting_hr(age, gender)
        conn = get_connection(self.db_path)
        conn.execute(
            """INSERT INTO athletes
               (id, last_name, first_name, middle_name, gender, birth_year,
                age, height_cm, weight_kg, resting_hr, max_hr,
                hrv_rmssd_baseline, avg_rr_ms, polar_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), d["last_name"], d["first_name"], d["middle_name"],
             gender, d["birth_year"], age, height, weight, resting,
             _estimate_max_hr(age), _estimate_hrv_rmssd(age),
             int(60000 / resting), d["polar_id"] or _generate_polar_id()))
        conn.commit()
        new_id = conn.execute("SELECT id FROM athletes ORDER BY rowid DESC").fetchone()[0]
        conn.close()
        self._load_athletes(select_id=new_id)

    def _edit_athlete(self):
        if not self.selected_athlete:
            return
        aid = self.selected_athlete[0]
        full = self._get_athlete_full(aid)
        if not full:
            return
        dlg = AthleteDialog(self, "Редактирование спортсмена", data=full)
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        age = datetime.date.today().year - d["birth_year"]
        conn = get_connection(self.db_path)
        conn.execute(
            """UPDATE athletes SET last_name=?, first_name=?, middle_name=?,
               gender=?, birth_year=?, age=?, height_cm=?, weight_kg=?, polar_id=?
               WHERE id=?""",
            (d["last_name"], d["first_name"], d["middle_name"], d["gender"],
             d["birth_year"], age, d["height_cm"], d["weight_kg"],
             d["polar_id"] or full["polar_id"], aid))
        conn.commit()
        conn.close()
        self._load_athletes(select_id=aid)

    def _delete_athlete(self):
        if not self.selected_athlete:
            return
        aid = self.selected_athlete[0]
        fio = f"{self.selected_athlete[1]} {self.selected_athlete[2]}"
        if not messagebox.askyesno("Удаление", f"Удалить {fio} и все его записи ЭКГ?"):
            return
        conn = get_connection(self.db_path)
        conn.execute("DELETE FROM ecg_records WHERE athlete_id=?", (aid,))
        conn.execute("DELETE FROM athletes WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        self._load_athletes()

    @staticmethod
    def _parse_header(raw):
        dt_str, polar = None, None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith('datetime='):
                dt_str = line.split('=', 1)[1]
            elif line.startswith('polar_id='):
                polar = line.split('=', 1)[1]
        return dt_str, polar

    def _import_ecg(self):
        path = filedialog.askopenfilename(
            title="Выберите файл записи ЭКГ",
            filetypes=[("Polar H10", "*.teamloggerh10 *.txt"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
            return

        dt_str, polar = self._parse_header(raw)
        try:
            dt = datetime.datetime.strptime(dt_str, "%Y.%m.%d %H:%M:%S")
        except Exception:
            dt = datetime.datetime.now().replace(microsecond=0)

        athlete = next((a for a in self.athletes if a[5] == polar), None)
        if athlete is None:
            if not self.selected_athlete:
                messagebox.showwarning("Внимание", "Устройство не найдено, спортсмен не выбран.")
                return
            fio = f"{self.selected_athlete[1]} {self.selected_athlete[2]}"
            if messagebox.askyesno("Устройство не найдено",
                                   f"Устройство {polar} отсутствует.\nПривязать к «{fio}»?"):
                athlete = self.selected_athlete
            else:
                return

        aid = athlete[0]
        recorded_at = dt.isoformat(sep=" ")
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM ecg_records WHERE athlete_id=? AND recorded_at=?",
                    (aid, recorded_at))
        if cur.fetchone():
            conn.close()
            messagebox.showinfo("Импорт", "Эта запись уже есть в базе.")
            return

        rr = parse_rr(raw)
        m = calc_metrics(rr) if rr else None
        s = calc_stress(rr) if rr else None
        duration = sum(rr) / 1000.0 if rr else 0.0
        cur.execute(
            """INSERT INTO ecg_records
               (athlete_id, recorded_at, duration_seconds, profile, raw_data,
                mean_hr, rmssd, sdnn, status, stress_si)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (aid, recorded_at, duration, "import", raw,
             m["mean_hr"] if m else None, m["rmssd"] if m else None,
             m["sdnn"] if m else None, m["status"] if m else "ok",
             s["si"] if s else None))
        conn.commit()
        conn.close()
        messagebox.showinfo("Импорт", f"Запись добавлена:\n{dt:%d.%m.%Y %H:%M}")

        self._load_year_range()
        self._view_year = min(max(dt.year, self._min_year), self._max_year)
        self._load_athletes(select_id=aid)

    def _ensure_indexes(self):
        # Индексы уже создаются в SCHEMA (database.py)
        # Эта функция оставлена для совместимости
        pass

    def _load_year_range(self):
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT MIN(recorded_at), MAX(recorded_at) FROM ecg_records")
        mn, mx = cur.fetchone()
        conn.close()
        today = datetime.date.today().year
        self._min_year = int(mn[:4]) if mn else today
        self._max_year = max(int(mx[:4]) if mx else today, today)

    def _change_year(self, delta):
        new = self._view_year + delta
        if self._min_year <= new <= self._max_year:
            self._view_year = new
            self._selected_week = None
            if self.selected_athlete:
                self._draw_density(self.selected_athlete[0])
                self._draw_tp(self.selected_athlete[0])

    def _load_athletes(self, select_id=None):
        try:
            conn = get_connection(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT id, last_name, first_name, age, gender, polar_id "
                        "FROM athletes ORDER BY last_name, first_name")
            self.athletes = cur.fetchall()
            conn.close()

            for item in self.tree_athletes.get_children():
                self.tree_athletes.delete(item)
            for a in self.athletes:
                self.tree_athletes.insert("", "end", iid=a[0], values=(f"{a[1]} {a[2]}", a[3]))

            children = self.tree_athletes.get_children()
            if not children:
                return
            target = select_id if select_id in children else children[0]
            self.tree_athletes.selection_set(target)
            self.tree_athletes.focus(target)
            self._on_athlete_select(None)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить данные:\n{e}")

    def _on_athlete_select(self, event):
        sel = self.tree_athletes.selection()
        if not sel:
            return
        athlete_id = sel[0]
        self.selected_athlete = next((a for a in self.athletes if a[0] == athlete_id), None)
        if self.selected_athlete:
            self._show_athlete_details()
            self._draw_density(athlete_id)
            self._draw_tp(athlete_id)

    def _show_athlete_details(self):
        if not self.selected_athlete:
            return
        aid, last, first, age, gender, pid = self.selected_athlete
        self.label_details.configure(text=(
            f"👤 {last} {first}\nВозраст: {age} лет\n"
            f"Пол: {'Мужской' if gender == 'M' else 'Женский'}\nPolar ID: {pid}"))

    @staticmethod
    def _style_ax(ax):
        ax.set_facecolor(COL_BG_DARK)
        ax.tick_params(colors=COL_TEXT_LIGHT, labelsize=8)
        for s in ax.spines.values():
            s.set_color(COL_SPINE)

    @staticmethod
    def _mean(vals):
        return sum(vals) / len(vals) if vals else 0

    def _si_color(self, si):
        return {"низкий": COL_ONE, "умеренный": COL_WARN,
                "высокий": "#ff8c42", "перенапряжение": COL_CRIT
                }.get(stress_level(si), COL_TEXT_DIM)

    def _set_month_ticks(self, ax):
        ticks, names = [], []
        for m in range(1, 13):
            w = (datetime.date(self._view_year, m, 1) - self._year_start).days // 7
            if 0 <= w < 53:
                ticks.append(w)
                names.append(MONTHS_RU[m - 1])
        ax.set_xticks(ticks)
        ax.set_xticklabels(names)
        ax.set_xlim(0, 53)

    def _draw_tp(self, athlete_id):
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(ecg_records)")
        cols = {r[1] for r in cur.fetchall()}
        sel = "recorded_at, sdnn" + (", stress_si" if "stress_si" in cols else ", NULL")
        cur.execute("SELECT " + sel + " FROM ecg_records WHERE athlete_id=?", (athlete_id,))
        rows = cur.fetchall()
        conn.close()

        jan1 = datetime.date(self._view_year, 1, 1)
        dec31 = datetime.date(self._view_year, 12, 31)
        week_tp, day_tp, week_si, day_si = {}, {}, {}, {}
        for recorded_at, sdnn, si in rows:
            d = datetime.datetime.fromisoformat(recorded_at).date()
            if sdnn is not None:
                tp = sdnn * sdnn
                day_tp.setdefault(d.isoformat(), []).append(tp)
                if jan1 <= d <= dec31:
                    week_tp.setdefault((d - self._year_start).days // 7, []).append(tp)
            if si is not None:
                day_si.setdefault(d.isoformat(), []).append(si)
                if jan1 <= d <= dec31:
                    week_si.setdefault((d - self._year_start).days // 7, []).append(si)

        self.ax_tp_year.clear()
        self._style_ax(self.ax_tp_year)
        xs = [w for w in range(53) if w in week_tp]
        ys = [self._mean(week_tp[w]) for w in xs]
        self.ax_tp_year.bar(xs, ys, width=1.0, color=COL_TP_YEAR)
        self._set_month_ticks(self.ax_tp_year)
        self.ax_tp_year.set_ylabel("мс²", color=COL_TEXT_LIGHT)
        self.ax_tp_year.set_title(f"TP по неделям, {self._view_year}",
                                  color=COL_TEXT_LIGHT, fontsize=9)

        self.ax_tp_week.clear()
        self._style_ax(self.ax_tp_week)
        ys7 = [self._mean(day_tp.get((self._week_start + datetime.timedelta(days=d)).isoformat()))
               for d in range(7)] if self._week_start else [0] * 7
        self.ax_tp_week.bar(range(7), ys7, color=COL_TP_WEEK)
        self.ax_tp_week.set_xticks(range(7))
        self.ax_tp_week.set_xticklabels([d[0] for d in DAYS_RU], fontsize=7)
        if self._week_start:
            we = self._week_start + datetime.timedelta(days=6)
            self.ax_tp_week.set_title(f"{self._week_start:%d.%m}–{we:%d.%m}",
                                      color=COL_TEXT_LIGHT, fontsize=7)

        self.ax_si_year.clear()
        self._style_ax(self.ax_si_year)
        xs = [w for w in range(53) if w in week_si]
        ys = [self._mean(week_si[w]) for w in xs]
        self.ax_si_year.bar(xs, ys, width=1.0, color=[self._si_color(v) for v in ys])
        self._set_month_ticks(self.ax_si_year)
        self.ax_si_year.set_ylabel("ИС", color=COL_TEXT_LIGHT)
        self.ax_si_year.set_title(f"Стресс по неделям, {self._view_year}",
                                  color=COL_TEXT_LIGHT, fontsize=9)

        self.ax_si_week.clear()
        self._style_ax(self.ax_si_week)
        ys7 = [self._mean(day_si.get((self._week_start + datetime.timedelta(days=d)).isoformat()))
               for d in range(7)] if self._week_start else [0] * 7
        self.ax_si_week.bar(range(7), ys7, color=[self._si_color(v) for v in ys7])
        self.ax_si_week.set_xticks(range(7))
        self.ax_si_week.set_xticklabels([d[0] for d in DAYS_RU], fontsize=7)
        if self._week_start:
            we = self._week_start + datetime.timedelta(days=6)
            self.ax_si_week.set_title(f"{self._week_start:%d.%m}–{we:%d.%m}",
                                      color=COL_TEXT_LIGHT, fontsize=7)

        self.canvas_tp.draw()

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

    def _draw_density(self, athlete_id):
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT recorded_at, status FROM ecg_records WHERE athlete_id=?",
                    (athlete_id,))
        rows = cur.fetchall()
        conn.close()

        date_map, self._day_block_map = {}, {}
        for recorded_at, status in rows:
            dt = datetime.datetime.fromisoformat(recorded_at)
            dkey = dt.date().isoformat()
            bkey = (dkey, dt.hour // 3)
            for m in (date_map.setdefault(dkey, {"count": 0, "worst": None}),
                      self._day_block_map.setdefault(bkey, {"count": 0, "worst": None})):
                m["count"] += 1
                if status == 'crit':
                    m["worst"] = 'crit'
                elif status == 'warn' and m["worst"] != 'crit':
                    m["worst"] = 'warn'

        today = datetime.date.today()
        jan1 = datetime.date(self._view_year, 1, 1)
        dec31 = datetime.date(self._view_year, 12, 31)
        self._year_start = jan1 - datetime.timedelta(days=jan1.weekday())
        self.label_year.configure(text=str(self._view_year))

        s, c = self.step, self.cell
        self.canvas_year.delete('all')
        for m in range(1, 13):
            w = (datetime.date(self._view_year, m, 1) - self._year_start).days // 7
            if 0 <= w < 53:
                self.canvas_year.create_text(YEAR_X0 + w * s, 8, text=MONTHS_RU[m - 1],
                                             fill=COL_TEXT_DIM, anchor='w', font=('Segoe UI', 9))
        for w in range(53):
            for d in range(7):
                day = self._year_start + datetime.timedelta(weeks=w, days=d)
                x, y = YEAR_X0 + w * s, YEAR_Y0 + d * s
                if day > today or day < jan1 or day > dec31:
                    color = COL_FUTURE
                else:
                    base = COL_WEEKEND if d >= 5 else COL_WEEKDAY
                    info = date_map.get(day.isoformat())
                    color = self._cell_color(info["count"], info["worst"], base) if info else base
                self.canvas_year.create_rectangle(x, y, x + c, y + c, fill=color, outline='')

        if self._selected_week is not None:
            x = YEAR_X0 + self._selected_week * s
            self.canvas_year.create_rectangle(x - 1, YEAR_Y0 - 1, x + c + 1,
                                              YEAR_Y0 + 7 * s, outline=COL_SELECTION,
                                              width=1, tags='sel')

        if self._selected_week is None:
            anchor = dec31 if self._view_year < today.year else today - datetime.timedelta(days=7)
            self._draw_week(anchor - datetime.timedelta(days=anchor.weekday()))
        else:
            self._draw_week(self._year_start + datetime.timedelta(weeks=self._selected_week))

    def _draw_week(self, week_start):
        self._week_start = week_start
        today = datetime.date.today()
        s, c = self.step, self.cell
        self.canvas_week.delete('all')
        for b in range(8):
            self.canvas_week.create_text(WEEK_X0 - 4, WEEK_Y0 + b * s + c // 2,
                                         text=f"{b * 3:02d}", fill=COL_TEXT_DIM,
                                         anchor='e', font=('Segoe UI', 9))
        for d in range(7):
            day = week_start + datetime.timedelta(days=d)
            for b in range(8):
                x, y = WEEK_X0 + d * s, WEEK_Y0 + b * s
                if day > today:
                    color = COL_FUTURE
                else:
                    base = COL_WEEKEND if d >= 5 else COL_WEEKDAY
                    info = self._day_block_map.get((day.isoformat(), b))
                    color = self._cell_color(info["count"], info["worst"], base) if info else base
                self.canvas_week.create_rectangle(x, y, x + c, y + c, fill=color, outline='')
        week_end = week_start + datetime.timedelta(days=6)
        self.label_week_title.configure(text=f"Неделя {week_start:%d.%m}–{week_end:%d.%m}")

    def _on_year_click(self, event):
        w = (event.x - YEAR_X0) // self.step
        if 0 <= w < 53:
            self._selected_week = w
            self._draw_week(self._year_start + datetime.timedelta(weeks=w))
            self.canvas_year.delete('sel')
            x = YEAR_X0 + w * self.step
            self.canvas_year.create_rectangle(x - 1, YEAR_Y0 - 1, x + self.cell + 1,
                                              YEAR_Y0 + 7 * self.step, outline=COL_SELECTION,
                                              width=1, tags='sel')
            if self.selected_athlete:
                self._draw_tp(self.selected_athlete[0])


if __name__ == '__main__':
    # БД создастся автоматически если её нет
    app = ECGViewerApp()
    app.mainloop()