"""Диалоговые окна приложения."""
import datetime
import re
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
from tkcalendar import DateEntry, Calendar

from models import get_session, Athlete, ECGRecord, ECGRaw, Device

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_WEEKEND,
                   COL_ACCENT, COL_SELECTION, COL_CRIT, COL_DANGER_HOVER,
                   COL_ONE, COL_WARN, COL_NEUTRAL, COL_TEXT_DIM)

from app_constants import (ECG_FILE_EXTENSION, ECGLIST_DEFAULT_LIMIT,
                           BIO_SIMILARITY_WARN_PCT, BIO_SIMILARITY_CRIT_PCT)


class _ForegroundDateEntry(DateEntry):
    """DateEntry, который не пропадает при смене месяца/года."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rebuild_lock = False  # Блокировка от рекурсии
        # tkcalendar инициализирует _downarrow_name асинхронно (через таймер),
        # а _on_motion по наведению мыши может сработать раньше -> AttributeError.
        # Ставим безопасное значение по умолчанию, чтобы не падало до его определения.
        if not hasattr(self, "_downarrow_name"):
            self._downarrow_name = "__none__"

    def drop_down(self):
        super().drop_down()
        self._ensure_foreground()

    def _ensure_foreground(self, event=None):
        """Возвращает календарь на передний план."""
        try:
            if not hasattr(self, '_top_cal') or not self._top_cal.winfo_exists():
                return
            
            # Поднимаем окно наверх
            self._top_cal.lift()
            self._top_cal.attributes("-topmost", True)
            self._top_cal.attributes("-topmost", False)
            self._top_cal.focus_force()
            
            # Отслеживаем перестройку календаря (смена месяца/года)
            if not self._rebuild_lock:
                self._top_cal.bind('<Configure>', self._on_calendar_rebuild, add='+')
                
        except Exception:
            pass

    def _on_calendar_rebuild(self, event=None):
        """Срабатывает после перестройки календаря."""
        if self._rebuild_lock:
            return
        try:
            self._rebuild_lock = True
            # Ждем завершения перестройки и возвращаем окно наверх
            self.master.after(50, self._ensure_foreground)
        finally:
            # Снимаем блокировку через 100 мс
            self.master.after(100, self._release_lock)
            
    def _release_lock(self):
        self._rebuild_lock = False


class AthleteDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, data=None, db_path=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x545")  # ⚡ высота увеличена: отдельная строка под кнопку "Список ЭКГ"
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        # ⚡ ДОБАВЛЕНО: Сохраняем параметры для проверки и открытия биометрии
        self.db_path = db_path
        self.athlete_id = data.get("id") if data else None

        row = 0
        fields_top = [("last_name", "Фамилия"), ("first_name", "Имя"),
                      ("middle_name", "Отчество")]
        fields_bottom = [("height_cm", "Рост (см)"), ("weight_kg", "Вес (кг)"),
                         ("polar_id", "Polar ID")]

        self.entries = {}
        for key, label in fields_top:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, padx=12, pady=4, sticky="w")
            e = ctk.CTkEntry(self)
            e.grid(row=row, column=1, padx=12, pady=4, sticky="ew")
            e.configure(validate="key", validatecommand=(self.register(self._only_letters), "%P", key))
            e.bind("<FocusOut>", lambda ev, k=key: self._capitalize(k))
            self.entries[key] = e
            row += 1

        ctk.CTkLabel(self, text="Дата рождения").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        self.birth_date_entry = _ForegroundDateEntry(
            self, width=12, date_pattern='dd-mm-yyyy',
            background=COL_BG_DARK, foreground=COL_TEXT_LIGHT,
            fieldbackground=COL_WEEKEND, borderwidth=0,
            selectbackground=COL_ACCENT, selectforeground=COL_SELECTION,
            year=2005, month=1, day=1,
            locale="ru_RU",
            showothermonthdays=False,
        )
        self.birth_date_entry.grid(row=row, column=1, padx=12, pady=4, sticky="ew")
        row += 1

        for key, label in fields_bottom:
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, padx=12, pady=4, sticky="w")
            e = ctk.CTkEntry(self)
            e.grid(row=row, column=1, padx=12, pady=4, sticky="ew")
            if key in ("height_cm", "weight_kg"):
                e.configure(validate="key",
                            validatecommand=(self.register(self._only_nonneg_number), "%P"))
            self.entries[key] = e
            row += 1

        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Пол").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        self.gender_var = ctk.StringVar(value="м")
        ctk.CTkOptionMenu(self, values=["м", "ж"], variable=self.gender_var
                          ).grid(row=row, column=1, padx=12, pady=4, sticky="ew")
        row += 1

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ctk.CTkButton(btns, text="Сохранить", command=self._on_save).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Отмена", fg_color=COL_NEUTRAL,
                      command=self.destroy).pack(side="left", padx=6)
        row += 1

        # Кнопки действий с данными атлета (под Сохранить/Отмена)
        ecg_btn_row = ctk.CTkFrame(self, fg_color="transparent")
        ecg_btn_row.grid(row=row, column=0, columnspan=2, pady=(6, 10))
        self.btn_ecg_list = ctk.CTkButton(
            ecg_btn_row, text="📋 Список ЭКГ",
            command=self._open_ecg_list)
        self.btn_ecg_list.pack(side="left", padx=4)
        self.btn_template = ctk.CTkButton(
            ecg_btn_row, text="🧬 Сформировать шаблон",
            command=self._build_template)
        self.btn_template.pack(side="left", padx=4)
        # Для нового атлета ещё нет id — действия недоступны
        if not self.athlete_id:
            self.btn_ecg_list.configure(state="disabled")
            self.btn_template.configure(state="disabled")

        # Заполняем данные, если редактируем существующего атлета
        if data:
            for key in self.entries:
                self.entries[key].delete(0, "end")
            
            for key, _ in fields_top + fields_bottom:
                val = data.get(key)
                if val is not None and val != "":
                    self.entries[key].insert(0, str(val))
            
            if data.get("birth_date"):
                try:
                    d = data["birth_date"]
                    if isinstance(d, str):
                        d = datetime.date.fromisoformat(d)
                    self.birth_date_entry.set_date(d)
                except (ValueError, TypeError):
                    pass
            self.gender_var.set("м" if data.get("gender") == "M" else "ж" if data.get("gender") == "F" else "м")
        
        # ⚡ ДОБАВЛЕНО: Поднимаем диалог на передний план
        self._bring_to_front()
        
    # ---------- валидация ввода ----------
    def _bring_to_front(self):
        """Поднимает диалог поверх других окон и даёт фокус."""
        try:
            if not self.winfo_exists():
                return
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _only_letters(self, proposed, key):
        """Только буквы, пробелы и дефис для ФИО."""
        if not proposed:
            return True
        allowed = re.fullmatch(r"[А-Яа-яЁёA-Za-z\s-]*", proposed)
        return bool(allowed)

    def _capitalize(self, key):
        """Первая буква заглавная, остальные — строчные."""
        e = self.entries.get(key)
        if not e:
            return
        text = e.get().strip()
        if text:
            e.delete(0, "end")
            e.insert(0, text[0].upper() + text[1:].lower())

    def _only_date_chars(self, proposed):
        """Разрешены только цифры и дефисы для даты."""
        if not proposed:
            return True
        return bool(re.fullmatch(r"[0-9-]*", proposed))

    def _only_nonneg_number(self, proposed):
        """Только неотрицательные числа (целые или дробные)."""
        if not proposed:
            return True
        return bool(re.fullmatch(r"\d*\.?\d*", proposed))

    def _open_ecg_list(self):
        """Открывает журнал ЭКГ, отфильтрованный по текущему атлету."""
        if not self.athlete_id:
            return
        ECGJournal(self, athlete_id=self.athlete_id,
                   db_path=self.db_path, limit=ECGLIST_DEFAULT_LIMIT,
                   title="ЭКГ атлета")

    def _build_template(self):
        """Формирует биометрический шаблон атлета из его записей.

        Если записей недостаточно — показывает соответствующее сообщение.
        """
        if not self.athlete_id:
            return
        from ecg_biometrics import create_and_save_template
        self.btn_template.configure(state="disabled", text="Формирование...")
        self.update()
        try:
            success, message = create_and_save_template(self.db_path, self.athlete_id)
        finally:
            self.btn_template.configure(state="normal", text="🧬 Сформировать шаблон")
        if success:
            messagebox.showinfo("Шаблон", message, parent=self)
        else:
            messagebox.showwarning("Шаблон", message, parent=self)

    def _on_save(self):
        try:
            last = self.entries["last_name"].get().strip()
            first = self.entries["first_name"].get().strip()
            if not last or not first:
                messagebox.showwarning("Проверка", "Фамилия и имя обязательны.")
                return

            bd = self.birth_date_entry.get_date()
            # Дополнительная защита: если tkcalendar вернул строку вместо даты
            if isinstance(bd, str):
                bd = datetime.date.fromisoformat(bd)
                
            if not datetime.date(1900, 1, 1) <= bd <= datetime.date.today():
                messagebox.showwarning("Проверка", "Некорректная дата рождения.")
                return

            def opt_num(key, cast):
                v = self.entries[key].get().strip()
                if not v:
                    return None
                try:
                    val = cast(v)
                    if val <= 0:
                        return None
                    return val
                except ValueError:
                    return None

            self.result = {
                "last_name": last, 
                "first_name": first,
                "middle_name": self.entries["middle_name"].get().strip(),
                "birth_date": bd,
                "gender": "M" if self.gender_var.get() == "м" else "F",
                "height_cm": opt_num("height_cm", int),
                "weight_kg": opt_num("weight_kg", float),
                "polar_id": self.entries["polar_id"].get().strip()
            }
            self.destroy()
            
        except Exception as e:
            # ⚡ ЕСЛИ ПРОИЗОШЛА ОШИБКА, МЫ ЕЁ УВИДИМ
            import traceback
            traceback.print_exc()
            messagebox.showerror("Ошибка сохранения", f"Произошла непредвиденная ошибка:\n{e}")

class ECGJournal(ctk.CTkToplevel):
    """Единый журнал записей ЭКГ (используется и из heatmap, и из главной формы).

    Режимы выборки:
      * интервал: date_from/date_to по recorded_at (из недельного heatmap),
        сортировка по умолчанию — время снятия (recorded_at ASC);
      * последние: limit по времени импорта (updated_at DESC), конкретный атлет
        или все (из главной формы).

    Сортировка — кликом по заголовку любой колонки, а также кнопками
    «По времени снятия» / «По времени импорта». Записи с низкой биологической
    схожестью с шаблоном подсвечиваются цветом (< WARN — жёлтым, < CRIT — красным).
    """

    DISPLAY_COLS = ("Атлет", "Прибор", "Время", "Импорт", "Сходство",
                    "ЧСС", "RMSSD", "SDNN", "ИС", "TP", "Статус")

    # имя колонки -> (ORM-таблица, атрибут) для order_by
    SORT_ATTR = {
        "Атлет": (Athlete, Athlete.last_name),
        "Прибор": (Device, Device.serial_number),
        "Время": (ECGRecord, ECGRecord.recorded_at),
        "Импорт": (ECGRecord, ECGRecord.updated_at),
        "Сходство": (ECGRecord, ECGRecord.bio_similarity_pct),
        "ЧСС": (ECGRecord, ECGRecord.mean_hr),
        "RMSSD": (ECGRecord, ECGRecord.rmssd),
        "SDNN": (ECGRecord, ECGRecord.sdnn),
        "ИС": (ECGRecord, ECGRecord.stress_si),
        "TP": (ECGRecord, ECGRecord.tp),
        "Статус": (ECGRecord, ECGRecord.status),
    }

    def __init__(self, parent, *, athlete_id=None, date_from=None, date_to=None,
                 limit=None, db_path=None, title="Журнал ЭКГ", on_change=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("1150x520")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.db_path = db_path or getattr(parent, "db_path", None)
        self.athlete_id = athlete_id
        self.date_from = date_from
        self.date_to = date_to
        self.limit = limit
        self.on_change = on_change

        # Сортировка по умолчанию: для интервала — по времени снятия (Время, ASC),
        # для "последних" — по времени импорта (Импорт, DESC).
        self._sort_col = "Время" if date_from is not None else "Импорт"
        self._sort_desc = date_from is None

        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=12, pady=8)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.tree = ttk.Treeview(frame, columns=self.DISPLAY_COLS, show="headings",
                                 height=14)
        widths = {"Атлет": 150, "Прибор": 120, "Время": 120, "Импорт": 120,
                  "Сходство": 80, "ЧСС": 70, "RMSSD": 70, "SDNN": 70,
                  "ИС": 70, "TP": 80, "Статус": 80}
        for c in self.DISPLAY_COLS:
            self.tree.heading(c, text=c, command=lambda _c=c: self._sort_by(_c))
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.tag_configure("warn", background=COL_WARN, foreground=COL_BG_DARK)
        self.tree.tag_configure("crit", background=COL_CRIT, foreground=COL_SELECTION)
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=6)
        ctk.CTkButton(btns, text="По времени снятия", width=110,
                      command=lambda: self._sort_preset("Время", False)).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="По времени импорта", width=130,
                      command=lambda: self._sort_preset("Импорт", True)).pack(side="left", padx=4)
        self.btn_export = ctk.CTkButton(btns, text=" Экспорт в файл",
                                        command=self._export, state="disabled")
        self.btn_export.pack(side="left", padx=4)
        self.btn_delete = ctk.CTkButton(btns, text="🗑 Удалить",
                                        command=self._delete, state="disabled",
                                        fg_color=COL_CRIT, hover_color=COL_DANGER_HOVER)
        self.btn_delete.pack(side="left", padx=4)
        self.btn_improve = ctk.CTkButton(btns, text="🎯 Улучшить сходство",
                                         command=self._improve_similarity, state="disabled")
        self.btn_improve.pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Закрыть", fg_color=COL_NEUTRAL,
                      command=self._safe_close).pack(side="left", padx=4)

        self.sort_label = ctk.CTkLabel(self, text="", text_color=COL_TEXT_DIM,
                                       font=ctk.CTkFont(size=11))
        self.sort_label.pack(pady=(0, 4))
        self.count_label = ctk.CTkLabel(self, text="", text_color=COL_TEXT_LIGHT,
                                        font=ctk.CTkFont(size=11))
        self.count_label.pack(pady=(0, 2))

        self._load()
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self._parent_watch = self.after(200, self._check_parent)

    # ---------- сортировка ----------
    def _sort_preset(self, col, desc):
        self._sort_col = col
        self._sort_desc = desc
        self._load()

    def _sort_by(self, col):
        """Клик по заголовку: переключает направление либо меняет колонку."""
        if col == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._load()

    # ---------- жизненный цикл окна ----------
    def _check_parent(self):
        try:
            if not self.master.winfo_exists():
                self.destroy()
                return
        except Exception:
            try:
                self.destroy()
            except Exception:
                pass
            return
        self._parent_watch = self.after(200, self._check_parent)

    def _safe_close(self):
        try:
            if hasattr(self, '_parent_watch'):
                self.after_cancel(self._parent_watch)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    # ---------- загрузка ----------
    def _base_query(self, session):
        q = (session.query(ECGRecord, Athlete, Device)
             .join(Athlete, ECGRecord.athlete_id == Athlete.id)
             .outerjoin(Device, ECGRecord.device_id == Device.id))
        if self.athlete_id:
            q = q.filter(ECGRecord.athlete_id == self.athlete_id)
        if self.date_from is not None and self.date_to is not None:
            dt_from = self.date_from.strftime("%Y-%m-%d %H:%M:%S")
            dt_to = self.date_to.strftime("%Y-%m-%d %H:%M:%S")
            q = q.filter(ECGRecord.recorded_at >= dt_from,
                         ECGRecord.recorded_at < dt_to)
        return q

    def _load(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        session = get_session(self.db_path)
        try:
            tbl, attr = self.SORT_ATTR[self._sort_col]
            order = attr.asc() if not self._sort_desc else attr.desc()
            q = self._base_query(session).order_by(order)
            if self.limit is not None:
                q = q.limit(self.limit)
            rows = q.all()

            for record, athlete, device in rows:
                self._insert(record, athlete, device)

            arrow = "↓" if self._sort_desc else "↑"
            self.count_label.configure(text=f"Записей: {len(rows)}")
            self.sort_label.configure(
                text=f"Сортировка: {self._sort_col} {arrow}  •  клик по заголовку меняет сортировку")
        finally:
            session.close()

    def _insert(self, rec, athlete, device):
        athlete_name = f"{athlete.last_name} {athlete.first_name} {athlete.middle_name or ''}".strip()
        device_name = f"{device.model} · {device.serial_number}" if device else "—"

        try:
            rec_at = datetime.datetime.fromisoformat(rec.recorded_at).strftime("%d.%m.%Y %H:%M")
        except Exception:
            rec_at = rec.recorded_at if rec.recorded_at else ""

        updated_str = ""
        if rec.updated_at:
            if isinstance(rec.updated_at, datetime.datetime):
                updated_str = rec.updated_at.strftime("%d.%m.%Y %H:%M")
            else:
                updated_str = str(rec.updated_at)[:16]

        sim = f"{rec.bio_similarity_pct:.0f}" if rec.bio_similarity_pct is not None else "—"

        tags = tuple([str(rec.id)])
        if rec.bio_similarity_pct is not None:
            if rec.bio_similarity_pct < BIO_SIMILARITY_CRIT_PCT:
                tags += ("crit",)
            elif rec.bio_similarity_pct < BIO_SIMILARITY_WARN_PCT:
                tags += ("warn",)

        self.tree.insert("", "end", iid=str(rec.id), tags=tags, values=(
            athlete_name, device_name, rec_at, updated_str, sim,
            f"{rec.mean_hr:.0f}" if rec.mean_hr is not None else "",
            f"{rec.rmssd:.1f}" if rec.rmssd is not None else "",
            f"{rec.sdnn:.1f}" if rec.sdnn is not None else "",
            f"{rec.stress_si:.0f}" if rec.stress_si is not None else "",
            f"{rec.tp:.0f}" if rec.tp is not None else "",
            rec.status or "",
        ))

    # ---------- действия ----------
    def _on_select(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_export.configure(state=state)
        self.btn_delete.configure(state=state)
        self.btn_improve.configure(state=state)

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _improve_similarity(self):
        """Открывает диалог выбора лучшего атлета для записи и переназначает её."""
        rid = self._selected_id()
        if rid is None:
            return

        def on_apply(record_id, new_athlete_id, prob):
            session = get_session(self.db_path)
            try:
                rec = session.get(ECGRecord, record_id)
                if rec is None:
                    return
                rec.athlete_id = new_athlete_id
                rec.bio_similarity_pct = round(prob * 100, 2) if prob is not None else None
                session.commit()
            finally:
                session.close()
            self._load()
            try:
                self.winfo_toplevel().event_generate("<<ECGDataChanged>>", when="tail")
            except Exception:
                pass

        SimilarityDialog(self, self.db_path, rid, on_apply=on_apply)

    def _export(self):
        rid = self._selected_id()
        if rid is None:
            return

        session = get_session(self.db_path)
        try:
            rec = session.get(ECGRecord, rid)
            if rec is None or rec.raw is None or not rec.raw.raw_data:
                messagebox.showwarning(
                    "Экспорт",
                    "Для этой записи нет сырых данных (raw_data).\n"
                    "Запись была создана без сохранения raw."
                )
                return
            rec_at = rec.recorded_at
            raw = rec.raw.raw_data
        finally:
            session.close()

        default_name = rec_at.replace(":", "-").replace(" ", "_") + ECG_FILE_EXTENSION
        path = filedialog.asksaveasfilename(
            title="Сохранить запись ЭКГ",
            initialfile=default_name,
            filetypes=[("Polar H10", f"*{ECG_FILE_EXTENSION}"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
            messagebox.showinfo("Экспорт", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")

    def _delete(self):
        rid = self._selected_id()
        if rid is None:
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранную запись ЭКГ?"):
            return

        session = get_session(self.db_path)
        try:
            rec = session.get(ECGRecord, rid)
            if rec is None:
                return
            session.delete(rec)
            session.commit()
        finally:
            session.close()

        self.tree.delete(str(rid))
        self._on_select()
        if self.on_change:
            self.on_change()
        # уведомляем главное окно (orchestrator обновит heatmap/графики)
        try:
            self.winfo_toplevel().event_generate("<<ECGDataChanged>>", when="tail")
        except Exception:
            pass

class SimilarityDialog(ctk.CTkToplevel):
    """Диалог «Улучшить сходство»: ранжирует атлетов по биометрии для записи ЭКГ.

    Атлеты перечислены по убыванию степени сходства (по вероятности совпадения),
    с метриками (расстояние, количество записей в шаблоне) — чтобы выбирать
    по всем признакам, а не только по фамилии.
    """

    COLS = ("ФИО", "Polar ID", "Сходство %", "Расстояние", "Записей в шаблоне", "Отметка")

    def __init__(self, parent, db_path, record_id, on_apply=None):
        super().__init__(parent)
        self.title("Улучшить сходство")
        self.geometry("780x480")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.db_path = db_path
        self.record_id = record_id
        self.on_apply = on_apply
        self.candidates = []

        ctk.CTkLabel(self, text="Выберите наиболее подходящего атлета (по биометрии)",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(padx=12, pady=(10, 4))

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.tree = ttk.Treeview(frame, columns=self.COLS, show="headings", height=12)
        widths = {"ФИО": 200, "Polar ID": 95, "Сходство %": 90, "Расстояние": 95,
                  "Записей в шаблоне": 70, "Отметка": 140}
        for c in self.COLS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.tag_configure("current", background=COL_ACCENT, foreground=COL_SELECTION)
        self.tree.tag_configure("relative", background=COL_WARN, foreground=COL_BG_DARK)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.info_label = ctk.CTkLabel(self, text="Загрузка...", text_color=COL_TEXT_DIM,
                                       font=ctk.CTkFont(size=11))
        self.info_label.pack(pady=(2, 2))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=8)
        self.btn_template = ctk.CTkButton(btns, text="🧬 Сформировать шаблон",
                                          command=self._build_template, state="disabled")
        self.btn_template.pack(side="left", padx=6)
        self.btn_apply = ctk.CTkButton(btns, text="Привязать к выбранному",
                                       command=self._apply, state="disabled")
        self.btn_apply.pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Отмена", fg_color=COL_NEUTRAL,
                      command=self.destroy).pack(side="left", padx=6)

        self._load()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _load(self):
        from ecg_biometrics import rank_athletes_for_record
        self.candidates = rank_athletes_for_record(self.db_path, self.record_id)
        if not self.candidates:
            self.info_label.configure(
                text="Нет данных: для записи нет сырых данных или шаблонов атлетов.")
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        for m in self.candidates:
            a = m['athlete']
            name = f"{a.last_name} {a.first_name} {a.middle_name or ''}".strip()
            marks = []
            if m['is_current']:
                marks.append("ТЕКУЩИЙ")
            if m['is_relative']:
                marks.append("родственник")
            tags = ()
            if m['is_current']:
                tags = ("current",)
            elif m['is_relative']:
                tags = ("relative",)
            self.tree.insert("", "end", iid=str(a.id), tags=tags, values=(
                name, a.polar_id or "—",
                f"{m['probability'] * 100:.0f}",
                f"{m['distance']:.3f}",
                m['records_used'],
                " · ".join(marks)))

        best = self.candidates[0]['athlete']
        self.info_label.configure(
            text=f"Лучший: {best.last_name} {best.first_name} "
                 f"({self.candidates[0]['probability'] * 100:.0f}%). "
                 f"Кандидатов: {len(self.candidates)}.")

    def _on_select(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_apply.configure(state=state)
        self.btn_template.configure(state=state)

    def _build_template(self):
        """Формирует биометрический шаблон для выбранного атлета.

        Если записей недостаточно — показываем соответствующее сообщение.
        """
        sel = self.tree.selection()
        if not sel:
            return
        aid = sel[0]

        from ecg_biometrics import create_and_save_template
        self.btn_template.configure(state="disabled", text="Формирование...")
        self.update()
        try:
            success, message = create_and_save_template(self.db_path, aid)
        finally:
            self.btn_template.configure(state="normal", text="🧬 Сформировать шаблон")

        if success:
            messagebox.showinfo("Шаблон", message, parent=self)
        else:
            messagebox.showwarning("Шаблон", message, parent=self)
        # обновляем рейтинг — новый шаблон появится в списке кандидатов
        self._load()

    def _apply(self):
        sel = self.tree.selection()
        if not sel:
            return
        new_aid = sel[0]
        m = next((x for x in self.candidates if x['athlete'].id == new_aid), None)
        if self.on_apply:
            self.on_apply(self.record_id, new_aid, m['probability'] if m else None)
        self.destroy()


class BiometricDialog(ctk.CTkToplevel):
    """Окно управления биометрическим шаблоном атлета."""
    def __init__(self, parent, db_path, athlete_id, athlete_name):
        super().__init__(parent)
        self.title(f"Биометрия: {athlete_name}")
        self.geometry("450x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.db_path = db_path
        self.athlete_id = athlete_id

        ctk.CTkLabel(self, text="Управление биометрическим шаблоном", 
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=15)

        self.status_lbl = ctk.CTkLabel(self, text="Загрузка статуса...", font=ctk.CTkFont(size=12))
        self.status_lbl.pack(pady=10)

        self.info_lbl = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color=COL_TEXT_DIM)
        self.info_lbl.pack(pady=5)

        self.btn_create = ctk.CTkButton(self, text="🧬 Сформировать / Обновить шаблон", 
                                        command=self._on_create, height=40)
        self.btn_create.pack(pady=20)

        ctk.CTkButton(self, text="Закрыть", fg_color=COL_NEUTRAL, command=self.destroy).pack(pady=10)

        self._update_status()

    def _update_status(self):
        from ecg_biometrics import get_saved_template, cfg
        shape, spec = get_saved_template(self.db_path, self.athlete_id)
        if shape is not None:
            self.status_lbl.configure(text="✅ Шаблон активен", text_color=COL_ONE)
            self.info_lbl.configure(text="Используется для проверки при импорте новых записей.")
            self.btn_create.configure(text="🔄 Обновить шаблон")
        else:
            self.status_lbl.configure(text="⚠️ Шаблон отсутствует", text_color=COL_WARN)
            self.info_lbl.configure(text=f"Для создания требуется минимум {cfg.MIN_RECORDS} записей ЭКГ.")
            self.btn_create.configure(text="✨ Создать шаблон")

    def _on_create(self):
        from ecg_biometrics import create_and_save_template
        self.btn_create.configure(state="disabled", text="Анализ записей...")
        self.update()
        
        def progress(msg):
            self.info_lbl.configure(text=msg)
            self.update()
            
        success, message = create_and_save_template(self.db_path, self.athlete_id, progress_cb=progress)
        
        if success:
            messagebox.showinfo("Успех", message, parent=self)
            self._update_status()
        else:
            messagebox.showerror("Ошибка", message, parent=self)
            self.btn_create.configure(state="normal")