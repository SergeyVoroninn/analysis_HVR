"""
atlets.py — панель списка спортсменов: отображение, добавление,
удаление, редактирование. Данные — в существующей БД (models.Athlete).
"""
import uuid

import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

from database import get_db_path
from models import get_session, Athlete
from dialogs import AthleteDialog
from athlete_generator import (
    _generate_polar_id, _estimate_height_cm, _estimate_weight_kg,
    _estimate_resting_hr, _estimate_max_hr, _estimate_hrv_rmssd, _calc_age)
from theme import COL_BG_WIDGET, COL_TEXT_LIGHT


class AthletesPanel(tk.Frame):
    """Левая панель: список спортсменов + кнопки CRUD + импорт."""

    def __init__(self, master, db_path=None, on_select=None, on_change=None):
        super().__init__(master, bg=COL_BG_WIDGET)
        self.db_path = db_path or get_db_path()
        self.on_select = on_select
        self.on_change = on_change
        self.on_import = None
        self.athletes = []

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        tk.Label(self, text="Спортсмены", bg=COL_BG_WIDGET, fg=COL_TEXT_LIGHT,
                 font=("Segoe UI", 14, "bold")).grid(row=0, column=0, pady=8)

        self.tree = ttk.Treeview(self, columns=("fio", "age"), show="headings")
        self.tree.heading("fio", text="ФИО")
        self.tree.heading("age", text="Возраст")
        self.tree.column("fio", width=130, stretch=True)
        self.tree.column("age", width=50, anchor="center", stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self._select_timer = None
        # Одинарный клик откладываем, чтобы двойной успел открыть диалог
        self.tree.bind("<<TreeviewSelect>>", self._on_select_scheduled)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        mgmt = ctk.CTkFrame(self, fg_color="transparent")
        mgmt.grid(row=2, column=0, pady=5)
        for text, cmd in (("＋", self.add), ("✎", self.edit), ("🗑", self.delete)):
            ctk.CTkButton(mgmt, text=text, width=40, command=cmd).pack(side="left", padx=3)

        self._imp_btn = ctk.CTkButton(self, text="⬇ Импорт записи ЭКГ",
                                      command=lambda: self.on_import and self.on_import())
        self._imp_btn.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 5))

        self.reload()

    # ------------------------------------------------ данные
    def _session(self):
        return get_session(self.db_path)

    def reload(self, select_id=None):
        session = self._session()
        try:
            rows = (session.query(Athlete)
                    .order_by(Athlete.last_name, Athlete.first_name).all())
            self.athletes = [(a.id, a.last_name, a.first_name,
                              _calc_age(a.birth_date), a.gender, a.polar_id)
                             for a in rows]
        finally:
            session.close()

        self.tree.delete(*self.tree.get_children())
        for a in self.athletes:
            self.tree.insert("", "end", iid=a[0], values=(f"{a[1]} {a[2]}", a[3]))

        children = self.tree.get_children()
        if children:
            target = select_id if select_id in children else children[0]
            self.tree.selection_set(target)
            self.tree.focus(target)

    def selected(self):
        """Текущий выбранный спортсмен (кортеж) или None."""
        sel = self.tree.selection()
        if not sel:
            return None
        return next((a for a in self.athletes if a[0] == sel[0]), None)

    def _on_select(self, event=None):
        if self.on_select:
            cur = self.selected()
            self.on_select(cur[0] if cur else None)

    def _on_select_scheduled(self, event=None):
        """Выбор атлета откладываем: даёт двойному клику открыть диалог первым."""
        if self._select_timer is not None:
            try:
                self.after_cancel(self._select_timer)
            except Exception:
                pass
        self._select_timer = self.after(350, self._on_select)

    def _on_double_click(self, event=None):
        """Двойной клик: отменяем отложенный выбор и открываем редактирование."""
        if self._select_timer is not None:
            try:
                self.after_cancel(self._select_timer)
                self._select_timer = None
            except Exception:
                pass
        self.edit()

    def _changed(self):
        if self.on_change:
            self.on_change()

    # ------------------------------------------------ CRUD
    def _get_full(self, aid):
        session = self._session()
        try:
            a = session.get(Athlete, aid)
            if a is None:
                return None
            return {k: getattr(a, k) for k in (
                "id", "last_name", "first_name", "middle_name", "gender",
                "birth_date", "height_cm", "weight_kg", "resting_hr",
                "max_hr", "hrv_rmssd_baseline", "avg_rr_ms", "polar_id")}
        finally:
            session.close()

    def add(self):
        dlg = AthleteDialog(self.winfo_toplevel(), "Новый спортсмен")
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        import datetime
        bd = d["birth_date"]
        if isinstance(bd, str):
            bd = datetime.date.fromisoformat(bd)
        age = _calc_age(bd)
        gender = d["gender"]
        height = d["height_cm"] or _estimate_height_cm(age, gender)
        weight = d["weight_kg"] or _estimate_weight_kg(height, age, gender)
        resting = _estimate_resting_hr(age, gender)

        athlete = Athlete(
            id=str(uuid.uuid4()),
            last_name=d["last_name"], first_name=d["first_name"],
            middle_name=d["middle_name"], gender=gender,
            birth_date=d["birth_date"], height_cm=height, weight_kg=weight,
            resting_hr=resting, max_hr=_estimate_max_hr(age),
            hrv_rmssd_baseline=_estimate_hrv_rmssd(age),
            avg_rr_ms=int(60000 / resting),
            polar_id=d["polar_id"] or _generate_polar_id(),
        )
        session = self._session()
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

        self.reload(select_id=new_id)
        self._changed()

    def edit(self):
        cur = self.selected()
        if not cur:
            return
        full = self._get_full(cur[0])
        if not full:
            return

        dlg = AthleteDialog(self.winfo_toplevel(), "Редактирование спортсмена",
                            data=full)
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            session = self._session()
            try:
                a = session.get(Athlete, cur[0])
                if a is not None:
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

        # После закрытия диалога — всегда выбираем кликнутого атлета
        # и перезагружаем его данные на графиках
        self.reload(select_id=cur[0])
        self._changed()

    def delete(self):
        cur = self.selected()
        if not cur:
            return
        session = self._session()
        try:
            a = session.get(Athlete, cur[0])
            if a is None:
                return
            session.delete(a)
            session.commit()
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось удалить:\n{e}")
            return
        finally:
            session.close()

        self.reload()
        self._changed()