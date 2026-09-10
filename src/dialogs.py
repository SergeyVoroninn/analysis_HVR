"""Диалоговые окна приложения."""
import datetime
import re
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
from tkcalendar import DateEntry, Calendar

from models import get_session, Athlete, ECGRecord, ECGRaw

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_WEEKEND,
                   COL_ACCENT, COL_SELECTION, COL_CRIT, COL_DANGER_HOVER)


class _ForegroundDateEntry(DateEntry):
    """DateEntry, который не пропадает при смене месяца/года."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rebuild_lock = False  # Блокировка от рекурсии

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
        self.geometry("380x520")  # ⚡ УВЕЛИЧИЛИ ВЫСОТУ (было 460), чтобы кнопка поместилась
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

        # ⚡ ТЕПЕРЬ ЭТО УСЛОВИЕ СРАБОТАЕТ КОРРЕКТНО
        if self.athlete_id and self.db_path:
            self.btn_bio = ctk.CTkButton(self, text="🧬 Биометрический шаблон", 
                                         command=self._open_biometrics,
                                         fg_color=COL_ACCENT,
                                         hover_color=COL_SELECTION)
            self.btn_bio.grid(row=row, column=0, columnspan=2, pady=(15, 5), sticky="ew")
            row += 1

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=2, pady=12)
        ctk.CTkButton(btns, text="Сохранить", command=self._on_save).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Отмена", fg_color="gray",
                      command=self.destroy).pack(side="left", padx=6)

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

    def _open_biometrics(self):
        # Импортируем здесь, чтобы избежать циклических зависимостей, если dialogs импортирует что-то еще
        from dialogs import BiometricDialog 
        
        last = self.entries["last_name"].get().strip()
        first = self.entries["first_name"].get().strip()
        athlete_name = f"{last} {first}" if last and first else "Атлет"
        
        BiometricDialog(self, self.db_path, self.athlete_id, athlete_name)    

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

class ECGListDialog(ctk.CTkToplevel):
    """Окно со списком ЭКГ за выбранный интервал (ORM-версия)."""

    # ⚡ ЗАМЕНИЛИ "Профиль" на "Обновлено"
    DISPLAY_COLS = ("Время", "Обновлено", "ЧСС", "RMSSD", "SDNN", "ИС", "TP", "Статус")

    def __init__(self, parent, athlete_id, date_from, date_to, title, on_change=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("720x480")
        self.transient(parent)
        self._calendar_open = False
        self._setup_grab()

        self.db_path = parent.db_path
        self.athlete_id = athlete_id
        self.date_from = date_from
        self.date_to = date_to
        self.on_change = on_change

        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=12, pady=8)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.tree = ttk.Treeview(frame, columns=self.DISPLAY_COLS, show="headings",
                                 height=14)
        for c in self.DISPLAY_COLS:
            if c == "Время":
                w = 110
            elif c == "Обновлено":  # ⚡ НОВАЯ КОЛОНКА
                w = 110
            elif c == "TP":
                w = 80
            else:
                w = 70
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=8)
        self.btn_export = ctk.CTkButton(btns, text=" Экспорт в файл",
                                        command=self._export, state="disabled")
        self.btn_export.pack(side="left", padx=4)
        self.btn_delete = ctk.CTkButton(btns, text="🗑 Удалить",
                                        command=self._delete, state="disabled",
                                        fg_color=COL_CRIT, 
                                        hover_color=COL_DANGER_HOVER)
        self.btn_delete.pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Закрыть", fg_color="gray",
                      command=self.destroy).pack(side="left", padx=4)

        self._load()
        self.protocol("WM_DELETE_WINDOW", self._safe_close)
        self._parent_watch = self.after(200, self._check_parent)

    def _setup_grab(self):
        """Grab_set включается только когда календарь закрыт."""
        if not self.winfo_exists():
            return
        try:
            for w in self.master.winfo_children():
                if hasattr(w, 'calendar') and w.winfo_exists():
                    self._calendar_open = True
                    return
            self._calendar_open = False
            self.grab_set()
        except Exception:
            pass

    def _check_parent(self):
        """Периодически проверяет, жив ли родитель."""
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
        """Безопасное закрытие диалога."""
        try:
            if hasattr(self, '_parent_watch'):
                self.after_cancel(self._parent_watch)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _load(self):
        """Загружает ЭКГ за интервал через ORM."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        dt_from = self.date_from.strftime("%Y-%m-%d %H:%M:%S")
        dt_to = self.date_to.strftime("%Y-%m-%d %H:%M:%S")

        session = get_session(self.db_path)
        try:
            records = (
                session.query(ECGRecord)
                .filter(ECGRecord.athlete_id == self.athlete_id,
                        ECGRecord.recorded_at >= dt_from,
                        ECGRecord.recorded_at < dt_to)
                .order_by(ECGRecord.recorded_at)
                .all()
            )

            for rec in records:
                #  ФОРМАТИРОВАНИЕ updated_at
                updated_str = ""
                if rec.updated_at:
                    if isinstance(rec.updated_at, datetime.datetime):
                        updated_str = rec.updated_at.strftime("%d.%m.%Y %H:%M")
                    else:
                        updated_str = str(rec.updated_at)[:16]
                
                self.tree.insert("", "end", iid=str(rec.id), values=(
                    rec.recorded_at[:16] if rec.recorded_at else "",
                    updated_str,  # ⚡ ВМЕСТО rec.profile
                    f"{rec.mean_hr:.0f}" if rec.mean_hr is not None else "",
                    f"{rec.rmssd:.1f}" if rec.rmssd is not None else "",
                    f"{rec.sdnn:.1f}" if rec.sdnn is not None else "",
                    f"{rec.stress_si:.0f}" if rec.stress_si is not None else "",
                    f"{rec.tp:.0f}" if rec.tp is not None else "",
                    rec.status or "",
                ))
        finally:
            session.close()

    def _on_select(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_export.configure(state=state)
        self.btn_delete.configure(state=state)

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _export(self):
        """Экспорт записи в файл через ORM (raw теперь в ECGRaw)."""
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

        default_name = rec_at.replace(":", "-").replace(" ", "_") + ".teamloggerh10"
        path = filedialog.asksaveasfilename(
            title="Сохранить запись ЭКГ",
            initialfile=default_name,
            filetypes=[("Polar H10", "*.teamloggerh10"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
            messagebox.showinfo("Экспорт", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")

    def _delete(self):
        """Удаление записи через ORM."""
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

        self.info_lbl = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.info_lbl.pack(pady=5)

        self.btn_create = ctk.CTkButton(self, text="🧬 Сформировать / Обновить шаблон", 
                                        command=self._on_create, height=40)
        self.btn_create.pack(pady=20)

        ctk.CTkButton(self, text="Закрыть", fg_color="gray", command=self.destroy).pack(pady=10)

        self._update_status()

    def _update_status(self):
        from ecg_biometrics import get_saved_template
        shape, spec = get_saved_template(self.db_path, self.athlete_id)
        if shape is not None:
            self.status_lbl.configure(text="✅ Шаблон активен", text_color="green")
            self.info_lbl.configure(text="Используется для проверки при импорте новых записей.")
            self.btn_create.configure(text="🔄 Обновить шаблон")
        else:
            self.status_lbl.configure(text="⚠️ Шаблон отсутствует", text_color="orange")
            self.info_lbl.configure(text=f"Для создания требуется минимум 7 записей ЭКГ.")
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