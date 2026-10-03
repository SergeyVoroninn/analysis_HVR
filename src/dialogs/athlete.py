"""Диалог добавления/редактирования атлета."""
import datetime
import re

import customtkinter as ctk

from theme import COL_BG_DARK, COL_TEXT_LIGHT, COL_WEEKEND, COL_ACCENT, COL_SELECTION

from .base import BaseDialog, CANCEL
from .common import _ForegroundDateEntry

from app_constants import ECGLIST_DEFAULT_LIMIT


class AthleteDialog(BaseDialog):
    def __init__(self, parent, title, data=None, db_path=None):
        super().__init__(parent, title=title, db_path=db_path,
                         size="380x545", modal=True)

        # ⚡ ДОБАВЛЕНО: Сохраняем параметры для проверки и открытия биометрии
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
            required=False,
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
        self.make_button(btns, "Сохранить", self._on_save, padx=6,
                         tooltip="Сохранить данные спортсмена")
        self.make_button(btns, "Отмена", self.destroy, kind=CANCEL, padx=6,
                         tooltip="Закрыть без сохранения")
        row += 1

        # Кнопки действий с данными атлета (под Сохранить/Отмена)
        ecg_btn_row = ctk.CTkFrame(self, fg_color="transparent")
        ecg_btn_row.grid(row=row, column=0, columnspan=2, pady=(6, 10))
        self.btn_ecg_list = self.make_button(ecg_btn_row, "📋 Список ЭКГ", self._open_ecg_list,
                                             padx=4, tooltip="Журнал записей ЭКГ атлета")
        self.btn_template = self.make_button(ecg_btn_row, "🧬 Сформировать шаблон", self._build_template,
                                             padx=4, tooltip="Создать биометрический шаблон по записям (мин. 8)")
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
        from .ecg_journal import ECGJournal
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
            _show_template_result(self, success, message)

    def _on_save(self):
        try:
            last = self.entries["last_name"].get().strip()
            first = self.entries["first_name"].get().strip()
            if not last or not first:
                from tkinter import messagebox
                messagebox.showwarning("Проверка", "Фамилия и имя обязательны.")
                return

            bd = self.birth_date_entry.get_date()
            # Дополнительная защита: если tkcalendar вернул строку вместо даты
            if isinstance(bd, str):
                bd = datetime.date.fromisoformat(bd)

            # Дата рождения необязательна: пустое поле сохраняется как None
            if bd is not None and not datetime.date(1900, 1, 1) <= bd <= datetime.date.today():
                from tkinter import messagebox
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
            from tkinter import messagebox
            messagebox.showerror("Ошибка сохранения", f"Произошла непредвиденная ошибка:\n{e}")


def _show_template_result(parent, success, message):
    """Единое отображение результата формирования шаблона."""
    import tkinter.messagebox as messagebox
    if success:
        messagebox.showinfo("Шаблон", message, parent=parent)
    else:
        messagebox.showwarning("Шаблон", message, parent=parent)