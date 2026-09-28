"""Диалог «Улучшить сходство»."""
import customtkinter as ctk
from tkinter import ttk

from theme import (COL_BG_DARK, COL_WARN, COL_ACCENT, COL_SELECTION, COL_TEXT_DIM)

from .base import BaseDialog, CANCEL


class SimilarityDialog(BaseDialog):
    """Диалог «Улучшить сходство»: ранжирует атлетов по биометрии для записи ЭКГ.

    Атлеты перечислены по убыванию степени сходства (по вероятности совпадения),
    с метриками (расстояние, количество записей в шаблоне) — чтобы выбирать
    по всем признакам, а не только по фамилии.
    """

    COLS = ("ФИО", "Polar ID", "Сходство %", "Расстояние", "Записей в шаблоне", "Отметка")

    def __init__(self, parent, db_path, record_id, on_apply=None):
        super().__init__(parent, title="Улучшить сходство", db_path=db_path,
                         size="780x480", resizable=(True, True), modal=True)

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

        btns = self.make_button_bar(self, pady=8)
        self.btn_apply = self.make_button(btns, "Привязать к выбранному",
                                          self._apply, state="disabled", padx=6,
                                          tooltip="Переназначить запись выбранному атлету")
        self.make_button(btns, "Отмена", self.destroy, kind=CANCEL, padx=6,
                         tooltip="Закрыть без изменений")

        self._load()

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

    def _apply(self):
        sel = self.tree.selection()
        if not sel:
            return
        new_aid = sel[0]
        m = next((x for x in self.candidates if x['athlete'].id == new_aid), None)
        if self.on_apply:
            self.on_apply(self.record_id, new_aid, m['probability'] if m else None)
        self.destroy()