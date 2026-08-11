"""Диалоговые окна приложения."""
import datetime
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
from tkcalendar import DateEntry

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_WEEKEND,
                   COL_ACCENT, COL_SELECTION)
from database import get_connection


class AthleteDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, data=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x460")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

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
            self.entries[key] = e
            row += 1

        # Дата рождения через календарь
        ctk.CTkLabel(self, text="Дата рождения").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        self.birth_date_entry = DateEntry(
            self, width=12, date_pattern='dd-mm-yyyy',
            background=COL_BG_DARK, foreground=COL_TEXT_LIGHT,
            fieldbackground=COL_WEEKEND, borderwidth=0,
            selectbackground=COL_ACCENT, selectforeground=COL_SELECTION,
            year=2005, month=1, day=1)
        self.birth_date_entry.grid(row=row, column=1, padx=12, pady=4, sticky="ew")
        row += 1

        for key, label in fields_bottom:
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
            for key, _ in fields_top + fields_bottom:
                if data.get(key) is not None:
                    self.entries[key].insert(0, str(data[key]))
            if data.get("birth_date"):
                try:
                    self.birth_date_entry.set_date(
                        datetime.date.fromisoformat(str(data["birth_date"])))
                except ValueError:
                    pass
            self.gender_var.set(data.get("gender", "M"))

    def _on_save(self):
        last = self.entries["last_name"].get().strip()
        first = self.entries["first_name"].get().strip()
        if not last or not first:
            messagebox.showwarning("Проверка", "Фамилия и имя обязательны.")
            return

        bd = self.birth_date_entry.get_date()
        if not datetime.date(1900, 1, 1) <= bd <= datetime.date.today():
            messagebox.showwarning("Проверка", "Некорректная дата рождения.")
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
                       "birth_date": bd.isoformat(),
                       "gender": self.gender_var.get(),
                       "height_cm": opt_num("height_cm", int),
                       "weight_kg": opt_num("weight_kg", float),
                       "polar_id": self.entries["polar_id"].get().strip()}
        self.destroy()

class ECGListDialog(ctk.CTkToplevel):
    """Окно со списком ЭКГ за выбранный интервал."""

    DISPLAY_COLS = ("Время", "Профиль", "ЧСС", "RMSSD", "SDNN", "ИС", "Статус")

    def __init__(self, parent, athlete_id, date_from, date_to, title,
                 on_change=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("720x480")
        self.transient(parent)
        self.grab_set()

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
            w = 90 if c == "Время" else 70
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=8)
        self.btn_export = ctk.CTkButton(btns, text="⬇ Экспорт в файл",
                                        command=self._export, state="disabled")
        self.btn_export.pack(side="left", padx=4)
        self.btn_delete = ctk.CTkButton(btns, text="🗑 Удалить",
                                        command=self._delete, state="disabled",
                                        fg_color="#da3633", hover_color="#b12b2b")
        self.btn_delete.pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Закрыть", fg_color="gray",
                      command=self.destroy).pack(side="left", padx=4)

        self._load()

    def _load(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """SELECT id, recorded_at, profile, mean_hr, rmssd, sdnn,
                      stress_si, status
               FROM ecg_records
               WHERE athlete_id=? AND recorded_at >= ? AND recorded_at < ?
               ORDER BY recorded_at""",
            (self.athlete_id,
             self.date_from.isoformat(sep=" "),
             self.date_to.isoformat(sep=" ")),
        )
        rows = cur.fetchall()
        conn.close()

        for r in rows:
            rid, rec, prof, hr, rmssd, sdnn, si, status = r
            self.tree.insert("", "end", iid=str(rid), values=(
                rec[:16] if rec else "",
                prof or "",
                f"{hr:.0f}" if hr is not None else "",
                f"{rmssd:.1f}" if rmssd is not None else "",
                f"{sdnn:.1f}" if sdnn is not None else "",
                f"{si:.0f}" if si is not None else "",
                status or "",
            ))

    def _on_select(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_export.configure(state=state)
        self.btn_delete.configure(state=state)

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _export(self):
        rid = self._selected_id()
        if rid is None:
            return
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT recorded_at, raw_data FROM ecg_records WHERE id=?", (rid,))
        row = cur.fetchone()
        conn.close()
        if not row or not row[1]:
            messagebox.showwarning("Экспорт", "Нет raw_data для этой записи.")
            return
        rec_at, raw = row
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
        rid = self._selected_id()
        if rid is None:
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранную запись ЭКГ?"):
            return
        conn = get_connection(self.db_path)
        conn.execute("DELETE FROM ecg_records WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        self.tree.delete(str(rid))
        self._on_select()
        if self.on_change:
            self.on_change()