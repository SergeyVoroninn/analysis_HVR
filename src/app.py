"""
Приложение для просмотра базы данных ЭКГ.
Один скрытый корень Tk: заставка и приложение — Toplevel-окна.
"""
import os
import sys
import uuid
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

from splash import SplashScreen
from theme import (COL_ACCENT, COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT,
                   COL_TEXT_DIM, COL_SPINE, COL_SELECTION, COL_WEEKDAY,
                   COL_WEEKEND, COL_FUTURE, COL_ONE, COL_MULTI, COL_WARN,
                   COL_CRIT, COL_TP_YEAR, COL_TP_WEEK)

YEAR_X0, YEAR_Y0 = 5, 18
WEEK_X0, WEEK_Y0 = 28, 5

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

def _load_heavy(pump=None):
    """Тяжёлые импорты вызываются, когда заставка уже на экране."""
    # Получаем путь к текущему файлу
    if getattr(sys, 'frozen', False):
        # Запущено из exe
        app_dir = os.path.dirname(sys.executable)
        scripts_dir = os.path.join(app_dir, '_internal', 'scripts')
    else:
        # Запущено из исходников
        app_dir = os.path.dirname(os.path.abspath(__file__))
        scripts_dir = os.path.join(app_dir, "scripts")
    
    # Добавляем все возможные пути
    for path in [app_dir, scripts_dir]:
        if path not in sys.path:
            sys.path.insert(0, path)
    
    print(f"📂 Пути для импорта: {sys.path[:3]}")  # для отладки

    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from sqlalchemy import func
    from analysis import parse_rr, calc_metrics, calc_stress, stress_level
    
    try:
        from athlete_generator import (
            _generate_polar_id, _estimate_height_cm, _estimate_weight_kg,
            _estimate_resting_hr, _estimate_max_hr, _estimate_hrv_rmssd, _calc_age)
    except ImportError as e:
        print(f"❌ athlete_generator не найден!")
        print(f"   Проверяем файлы:")
        print(f"   - {os.path.join(app_dir, 'athlete_generator.py')}: {'✅' if os.path.exists(os.path.join(app_dir, 'athlete_generator.py')) else '❌'}")
        print(f"   - {os.path.join(scripts_dir, 'athlete_generator.py')}: {'✅' if os.path.exists(os.path.join(scripts_dir, 'athlete_generator.py')) else '❌'}")
        raise

    from database import get_db_path
    from models import get_session, Athlete, ECGRecord
    from dialogs import AthleteDialog, ECGListDialog

    globals().update({
        'Figure': Figure,
        'FigureCanvasTkAgg': FigureCanvasTkAgg,
        'func': func,
        'parse_rr': parse_rr,
        'calc_metrics': calc_metrics,
        'calc_stress': calc_stress,
        'stress_level': stress_level,
        '_generate_polar_id': _generate_polar_id,
        '_estimate_height_cm': _estimate_height_cm,
        '_estimate_weight_kg': _estimate_weight_kg,
        '_estimate_resting_hr': _estimate_resting_hr,
        '_estimate_max_hr': _estimate_max_hr,
        '_estimate_hrv_rmssd': _estimate_hrv_rmssd,
        '_calc_age': _calc_age,
        'get_db_path': get_db_path,
        'get_session': get_session,
        'Athlete': Athlete,
        'ECGRecord': ECGRecord,
        'AthleteDialog': AthleteDialog,
        'ECGListDialog': ECGListDialog,
    })

    if pump:
        pump()

class ECGViewerApp(ctk.CTkToplevel):
    def __init__(self, master, db_path=None):
        super().__init__(master)

        self.report_callback_exception = lambda *args: None

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
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._load_year_range()
        self._load_athletes()

    def _on_closing(self):
        """Закрытие с подавлением Tcl-ошибок."""
        try:
            # Подавляем ошибки от after callbacks
            self.report_callback_exception = lambda *args: None
            self.quit()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    # =========================================================
    # Интерфейс
    # =========================================================
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
        self.canvas_week.bind("<Button-1>", self._on_week_click)
        self.canvas_week.bind("<Double-Button-1>", self._on_week_click)

        self.tp_frame = ctk.CTkFrame(self.right_panel)
        self.tp_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        self.tp_frame.grid_rowconfigure(1, weight=1)
        self.tp_frame.grid_columnconfigure(0, weight=1)
        self.label_tp = ctk.CTkLabel(self.tp_frame, text="TP (мс²) и индекс стресса (ИС)",
                                     font=ctk.CTkFont(size=12))
        self.label_tp.grid(row=0, column=0, padx=10, pady=(6, 0), sticky="w")

        self.plt_area = ctk.CTkFrame(self.tp_frame, fg_color="transparent")
        self.plt_area.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        self.fig_tp = Figure(figsize=(9, 4.6), dpi=100)
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
        self.canvas_tp.mpl_connect("button_press_event", self._on_tp_click)
        self.canvas_tp.mpl_connect("button_press_event", self._on_week_plot_click)

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
        self.fig_tp.tight_layout()
        self.canvas_tp.draw_idle()

    # =========================================================
    # CRUD спортсмена (ORM)
    # =========================================================
    def _get_athlete_full(self, aid):
        """Возвращает dict полей спортсмена или None."""
        session = get_session(self.db_path)
        try:
            a = session.get(Athlete, aid)
            if a is None:
                return None
            return {
                "id": a.id,
                "last_name": a.last_name,
                "first_name": a.first_name,
                "middle_name": a.middle_name,
                "gender": a.gender,
                "birth_date": a.birth_date,
                "height_cm": a.height_cm,
                "weight_kg": a.weight_kg,
                "resting_hr": a.resting_hr,
                "max_hr": a.max_hr,
                "hrv_rmssd_baseline": a.hrv_rmssd_baseline,
                "avg_rr_ms": a.avg_rr_ms,
                "polar_id": a.polar_id,
            }
        finally:
            session.close()

    def _create_athlete(self):
        dlg = AthleteDialog(self, "Новый спортсмен")
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        bd = datetime.date.fromisoformat(d["birth_date"])
        age = _calc_age(bd)
        gender = d["gender"]
        height = d["height_cm"] or _estimate_height_cm(age, gender)
        weight = d["weight_kg"] or _estimate_weight_kg(height, age, gender)
        resting = _estimate_resting_hr(age, gender)

        athlete = Athlete(
            id=str(uuid.uuid4()),
            last_name=d["last_name"],
            first_name=d["first_name"],
            middle_name=d["middle_name"],
            gender=gender,
            birth_date=d["birth_date"],
            height_cm=height,
            weight_kg=weight,
            resting_hr=resting,
            max_hr=_estimate_max_hr(age),
            hrv_rmssd_baseline=_estimate_hrv_rmssd(age),
            avg_rr_ms=int(60000 / resting),
            polar_id=d["polar_id"] or _generate_polar_id(),
        )

        session = get_session(self.db_path)
        try:
            session.add(athlete)
            session.commit()
            new_id = athlete.id
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось создать спортсмена:\n{e}")
            return
        finally:
            session.close()

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

        session = get_session(self.db_path)
        try:
            a = session.get(Athlete, aid)
            if a is None:
                return
            a.last_name = d["last_name"]
            a.first_name = d["first_name"]
            a.middle_name = d["middle_name"]
            a.gender = d["gender"]
            a.birth_date = d["birth_date"]
            a.height_cm = d["height_cm"]
            a.weight_kg = d["weight_kg"]
            a.polar_id = d["polar_id"] or full["polar_id"]
            session.commit()
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")
        finally:
            session.close()

        self._load_athletes(select_id=aid)

    def _delete_athlete(self):
        if not self.selected_athlete:
            return
        aid = self.selected_athlete[0]
        fio = f"{self.selected_athlete[1]} {self.selected_athlete[2]}"
        if not messagebox.askyesno("Удаление", f"Удалить {fio} и все его записи ЭКГ?"):
            return

        session = get_session(self.db_path)
        try:
            a = session.get(Athlete, aid)
            if a is None:
                return
            # cascade="all, delete-orphan" удалит связанные ecg_records
            session.delete(a)
            session.commit()
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось удалить:\n{e}")
        finally:
            session.close()

        self._load_athletes()

    # =========================================================
    # Импорт ЭКГ
    # =========================================================
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
            filetypes=[("Polar H10", "*.teamloggerh10"), ("Все файлы", "*.*")])
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

        recorded_at = dt.isoformat(sep=" ")

        session = get_session(self.db_path)
        try:
            # === Ищем запись ТОЛЬКО по времени (без спортсмена) ===
            existing = (session.query(ECGRecord)
                        .filter(ECGRecord.recorded_at == recorded_at)
                        .first())

            if existing:
                # Запись с таким временем уже есть
                if existing.athlete_id == (self.selected_athlete[0] if self.selected_athlete else None):
                    # Тот же спортсмен — это дубликат
                    messagebox.showinfo("Импорт", "Эта запись уже есть в базе.")
                    return
                else:
                    # Другой спортсмен — спрашиваем про перепривязку
                    other_athlete = session.get(Athlete, existing.athlete_id)
                    other_fio = f"{other_athlete.last_name} {other_athlete.first_name}" if other_athlete else "неизвестный"
                    
                    current_fio = f"{self.selected_athlete[1]} {self.selected_athlete[2]}" if self.selected_athlete else "не выбран"
                    
                    if messagebox.askyesno(
                        "Запись уже существует",
                        f"Запись от {dt:%d.%m.%Y %H:%M} уже привязана к спортсмену «{other_fio}».\n\n"
                        f"Перенести её к «{current_fio}»?"
                    ):
                        # Перепривязываем
                        if self.selected_athlete:
                            existing.athlete_id = self.selected_athlete[0]
                            session.commit()
                            messagebox.showinfo("Импорт", f"Запись перенесена к «{current_fio}».")
                            self._load_year_range()
                            self._view_year = min(max(dt.year, self._min_year), self._max_year)
                            self._load_athletes(select_id=self.selected_athlete[0])
                        return
                    else:
                        return

            # === Записи нет — добавляем новую ===
            # Поиск спортсмена по polar_id
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

            rr = parse_rr(raw)
            m = calc_metrics(rr) if rr else None
            s = calc_stress(rr) if rr else None
            duration = sum(rr) / 1000.0 if rr else 0.0

            rec = ECGRecord(
                athlete_id=aid,
                recorded_at=recorded_at,
                duration_seconds=duration,
                profile="import",
                raw_data=raw,
                mean_hr=m["mean_hr"] if m else None,
                rmssd=m["rmssd"] if m else None,
                sdnn=m["sdnn"] if m else None,
                status=m["status"] if m else "ok",
                stress_si=s["si"] if s else None,
            )
            session.add(rec)
            session.commit()

        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить запись:\n{e}")
            return
        finally:
            session.close()

        messagebox.showinfo("Импорт", f"Запись добавлена:\n{dt:%d.%m.%Y %H:%M}")

        self._load_year_range()
        self._view_year = min(max(dt.year, self._min_year), self._max_year)
        self._load_athletes(select_id=aid)

    # =========================================================
    # Загрузка диапазонов и списка спортсменов
    # =========================================================
    def _load_year_range(self):
        session = get_session(self.db_path)
        try:
            row = (session.query(func.min(ECGRecord.recorded_at),
                                 func.max(ECGRecord.recorded_at))
                   .first())
        finally:
            session.close()

        mn, mx = row if row else (None, None)
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
            session = get_session(self.db_path)
            try:
                rows = (session.query(Athlete)
                        .order_by(Athlete.last_name, Athlete.first_name)
                        .all())
                self.athletes = [
                    (a.id, a.last_name, a.first_name,
                     _calc_age(a.birth_date), a.gender, a.polar_id)
                    for a in rows
                ]
            finally:
                session.close()

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

    # =========================================================
    # Графики (ORM)
    # =========================================================
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
        session = get_session(self.db_path)
        try:
            rows = (session.query(ECGRecord.recorded_at,
                                  ECGRecord.sdnn,
                                  ECGRecord.stress_si)
                    .filter(ECGRecord.athlete_id == athlete_id)
                    .all())
        finally:
            session.close()

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
        self.ax_tp_year.bar(xs, ys, width=1.0, color=COL_TP_YEAR, align='edge')
        self._set_month_ticks(self.ax_tp_year)
        self.ax_tp_year.set_ylabel("мс²", color=COL_TEXT_LIGHT)
        self.ax_tp_year.set_title(f"TP по неделям, {self._view_year}",
                                  color=COL_TEXT_LIGHT, fontsize=9)

        self.ax_tp_week.clear()
        self._style_ax(self.ax_tp_week)
        ys7 = [self._mean(day_tp.get((self._week_start + datetime.timedelta(days=d)).isoformat()))
               for d in range(7)] if self._week_start else [0] * 7
        self.ax_tp_week.bar(range(7), ys7, color=COL_TP_WEEK, align='edge')
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
        self.ax_si_year.bar(xs, ys, width=1.0, color=[self._si_color(v) for v in ys], align='edge')
        self._set_month_ticks(self.ax_si_year)
        self.ax_si_year.set_ylabel("ИС", color=COL_TEXT_LIGHT)
        self.ax_si_year.set_title(f"Стресс по неделям, {self._view_year}",
                                  color=COL_TEXT_LIGHT, fontsize=9)

        self.ax_si_week.clear()
        self._style_ax(self.ax_si_week)
        ys7 = [self._mean(day_si.get((self._week_start + datetime.timedelta(days=d)).isoformat()))
               for d in range(7)] if self._week_start else [0] * 7
        self.ax_si_week.bar(range(7), ys7, color=[self._si_color(v) for v in ys7], align='edge')
        self.ax_si_week.set_xticks(range(7))
        self.ax_si_week.set_xticklabels([d[0] for d in DAYS_RU], fontsize=7)
        if self._week_start:
            we = self._week_start + datetime.timedelta(days=6)
            self.ax_si_week.set_title(f"{self._week_start:%d.%m}–{we:%d.%m}",
                                      color=COL_TEXT_LIGHT, fontsize=7)

        self.fig_tp.tight_layout()
        self.canvas_tp.draw_idle()

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
        session = get_session(self.db_path)
        try:
            rows = (session.query(ECGRecord.recorded_at, ECGRecord.status)
                    .filter(ECGRecord.athlete_id == athlete_id)
                    .all())
        finally:
            session.close()

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

    def _select_week(self, w):
        if not (0 <= w < 53):
            return
        self._selected_week = w
        self._draw_week(self._year_start + datetime.timedelta(weeks=w))

        self.canvas_year.delete('sel')
        x = YEAR_X0 + w * self.step
        self.canvas_year.create_rectangle(x - 1, YEAR_Y0 - 1, x + self.cell + 1,
                                          YEAR_Y0 + 7 * self.step,
                                          outline=COL_SELECTION, width=1, tags='sel')
        if self.selected_athlete:
            self._draw_tp(self.selected_athlete[0])

    def _on_year_click(self, event):
        w = (event.x - YEAR_X0) // self.step
        self._select_week(w)

    def _on_tp_click(self, event):
        if event.inaxes not in (self.ax_tp_year, self.ax_si_year):
            return
        if event.xdata is None:
            return
        w = int(event.xdata)
        self.after(0, lambda: self._select_week(w))

    def _on_week_click(self, event):
        d = (event.x - WEEK_X0) // self.step
        b = (event.y - WEEK_Y0) // self.step
        if not (0 <= d < 7 and 0 <= b < 8) or not self._week_start:
            return

        day = self._week_start + datetime.timedelta(days=d)

        # === НЕТ ЗАПИСЕЙ В БЛОКЕ — НЕ ОТКРЫВАЕМ ОКНО ===
        if (day.isoformat(), b) not in self._day_block_map:
            return

        dt_from = datetime.datetime.combine(day, datetime.time(b * 3, 0))
        dt_to = dt_from + datetime.timedelta(hours=3)
        title = f"ЭКГ за {day:%d.%m.%Y} {b*3:02d}:00–{(b*3+3)%24:02d}:00"
        self._open_ecg_list(dt_from, dt_to, title)

    def _on_week_plot_click(self, event):
        if event.inaxes not in (self.ax_tp_week, self.ax_si_week):
            return
        if event.xdata is None or not self._week_start:
            return
        d = int(event.xdata)
        if not (0 <= d < 7):
            return

        day = self._week_start + datetime.timedelta(days=d)

        # === НЕТ ЗАПИСЕЙ ЗА ДЕНЬ — НЕ ОТКРЫВАЕМ ОКНО ===
        day_iso = day.isoformat()
        if not any(k[0] == day_iso for k in self._day_block_map):
            return

        dt_from = datetime.datetime.combine(day, datetime.time(0, 0))
        dt_to = datetime.datetime.combine(day, datetime.time(23, 59, 59))
        title = f"ЭКГ за {day:%d.%m.%Y}"
        self.after(0, lambda: self._open_ecg_list(dt_from, dt_to, title))

    def _open_ecg_list(self, dt_from, dt_to, title):
        if not self.selected_athlete:
            return

        # === Если в интервале нет записей — окно не открывается ===
        session = get_session(self.db_path)
        try:
            count = (session.query(func.count(ECGRecord.id))
                     .filter(ECGRecord.athlete_id == self.selected_athlete[0],
                             ECGRecord.recorded_at >= dt_from.isoformat(sep=" "),
                             ECGRecord.recorded_at < dt_to.isoformat(sep=" "))
                     .scalar())
        finally:
            session.close()

        if not count:
            return

        # Защита от повторного открытия
        if getattr(self, "_ecg_list_dlg", None) is not None:
            try:
                if self._ecg_list_dlg.winfo_exists():
                    self._ecg_list_dlg.focus_set()
                    return
            except tk.TclError:
                self._ecg_list_dlg = None

        self._ecg_list_dlg = ECGListDialog(
            self,
            athlete_id=self.selected_athlete[0],
            date_from=dt_from,
            date_to=dt_to,
            title=title,
            on_change=self._on_ecg_list_changed)

    def _on_ecg_list_changed(self):
        if self.selected_athlete:
            aid = self.selected_athlete[0]
            self._draw_density(aid)
            self._draw_tp(aid)

if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    root.report_callback_exception = lambda *a: None

    splash = SplashScreen(root, show_ms=1500, auto_close=False)
    root.update()                      # заставка на экране

    _load_heavy(pump=root.update)

    # Окно строится, ПОКА заставка ещё видна
    app = ECGViewerApp(root)
    app.withdraw()                     # окно готово, но спрятано

    splash.close_splash()              # заставка уходит
    app.deiconify()                    # окно появляется МГНОВЕННО

    try:
        root.mainloop()
    finally:
        os._exit(0)