"""Единое окно биометрического сходства — список атлетов по убыванию совпадения."""
import customtkinter as ctk
from tkinter import ttk

from theme import (COL_BG_DARK, COL_WARN, COL_ACCENT, COL_SELECTION, COL_TEXT_DIM)

from .base import BaseDialog, CANCEL


class SimilarityDialog(BaseDialog):
    """Выбор атлета по биометрическому сходству.

    Единое окно для двух сценариев:
      * кнопка «Улучшить схожесть» в журнале ЭКГ — source = id записи;
      * слабое совпадение с шаблоном при импорте — source = raw-данные файла.

    В окне — сортированный по убыванию схожести список всех атлетов
    (probability), с отметкой текущего и родственников. Результат выбора:
      * через колбэк on_apply(athlete_id, probability);
      * через self.result = {"athlete_id": ..., "probability": ...}
        (None — если отменено), подходит для modal_loop().
    """

    COLS = ("ФИО", "Polar ID", "Сходство %", "Расстояние", "Записей в шаблоне", "Отметка")

    def __init__(self, parent, db_path, source, *,
                 candidates=None, current_athlete_id=None, on_apply=None,
                 title="Улучшить сходство",
                 prompt="Выберите наиболее подходящего атлета:"):
        super().__init__(parent, title=title, db_path=db_path,
                         size="780x480", resizable=(True, True), modal=True)

        self.on_apply = on_apply
        # source: int (id записи в БД) либо str (raw-фрагмент ЭКГ)
        if candidates is None:
            candidates = self._load_candidates(source, current_athlete_id)
        self.candidates = candidates

        ctk.CTkLabel(self, text=prompt,
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
        self.make_button(btns, "Отмена", self.close, kind=CANCEL, padx=6,
                         tooltip="Закрыть без изменений")

        self._load()

    def _load_candidates(self, source, current_athlete_id):
        """Загружает и ранжирует кандидатов по source (id записи или raw)."""
        from ecg_biometrics import rank_athletes_for_raw, rank_athletes_for_record
        if isinstance(source, int):
            return rank_athletes_for_record(self.db_path, source)
        return rank_athletes_for_raw(self.db_path, source, current_athlete_id)

    def _load(self):
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
        self.btn_apply.configure(state="normal" if sel else "disabled")

    def _apply(self):
        sel = self.tree.selection()
        if not sel:
            return
        aid = sel[0]
        m = next((x for x in self.candidates if x['athlete'].id == aid), None)
        if m is None:
            return
        if self.on_apply:
            self.on_apply(m['athlete'].id, m['probability'])
        self.result = {"athlete_id": m['athlete'].id, "probability": m['probability']}
        self.destroy()