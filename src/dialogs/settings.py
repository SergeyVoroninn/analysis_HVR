"""Окно настроек: выбор и порядок отображаемых метрик на графиках."""
import customtkinter as ctk
from tkinter import messagebox

from .base import BaseDialog, CANCEL, PRIMARY
from charts import ALL_METRICS, DEFAULT_METRIC_ORDER


class MetricsSettingsDialog(BaseDialog):
    """Окно настроек отображения метрик.

    Все метрики из реестра ALL_METRICS всегда видны в списке:
      * чекбокс включает/выключает метрику на графиках (не убирая её из списка);
      * кнопки ▲/▼ меняют порядок всех метрик в списке.

    self.result = список ключей ОТМЕЧЕННЫХ метрик в порядке их расположения
    в списке (или None, если нажата Отмена).
    """

    def __init__(self, parent, *, current_order=None):
        super().__init__(parent, title="Настройки отображения метрик",
                         size="420x480", resizable=(False, False), modal=True)

        if not current_order:
            current_order = DEFAULT_METRIC_ORDER
        # Все метрики в текущем порядке; недостающие добавляем в конец.
        self._order = []
        for k in DEFAULT_METRIC_ORDER + [k for k in ALL_METRICS]:
            if k not in self._order:
                self._order.append(k)
        # Включённые по умолчанию — те, что пришли из настроек (current_order) —
        # иначе все.
        enabled = set(current_order) if current_order else set(ALL_METRICS)
        self._enabled = {k: (k in enabled) for k in self._order}
        if current_order:
            # текущий переданный порядок отражаем в _order, сохраняя прочие метрики
            merged = list(current_order) + [k for k in self._order if k not in current_order]
            self._order = merged

        self.result = None

        ctk.CTkLabel(self, text="Метрики на графиках",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 4))
        ctk.CTkLabel(self, text="Отметьте метрики для отображения и настройте порядок.",
                     text_color="#9a9a9a", font=ctk.CTkFont(size=11)).pack(pady=(0, 8))

        # Список метрик: чекбокс + название слева, кнопки вверх/вниз справа.
        self._list = ctk.CTkFrame(self)
        self._list.pack(fill="both", expand=True, padx=12, pady=4)
        self._rebuild_list()

        # Кнопочная строка
        bar = self.make_button_bar(self, pady=8)
        self.make_button(bar, "Сохранить", self._on_save, kind=PRIMARY,
                         tooltip="Сохранить выбранные метрики и порядок")
        self.make_button(bar, "Отмена", self.close, kind=CANCEL,
                         tooltip="Закрыть без изменений")

        self._center_over_parent()

    # ---------------------------------------------------------- список
    def _rebuild_list(self):
        """Перестраивает список из self._order, сохраняя состояние чекбоксов."""
        for w in self._list.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        for idx, key in enumerate(self._order):
            spec = ALL_METRICS[key]
            row = ctk.CTkFrame(self._list, fg_color="transparent")
            row.pack(fill="x", pady=1, padx=2)

            cb = ctk.CTkCheckBox(
                row,
                text=f"{spec.name} ({spec.ylabel})",
                variable=ctk.BooleanVar(value=self._enabled[key]),
                command=lambda k=key: self._on_toggle(k),
            )
            cb.pack(side="left", padx=4, pady=2)
            # цветной маркер метрики (всегда строка)
            marker = ctk.CTkLabel(row, text="●", text_color=spec.marker_color, width=16)
            marker.pack(side="left")

            up = ctk.CTkButton(row, text="▲", width=28,
                               command=lambda k=key: self._move(k, -1))
            up.pack(side="right", padx=2)
            down = ctk.CTkButton(row, text="▼", width=28,
                                 command=lambda k=key: self._move(k, 1))
            down.pack(side="right", padx=2)

    def _on_toggle(self, key):
        """Переключает включённость метрики (метрика остаётся в списке)."""
        self._enabled[key] = not self._enabled[key]

    def _move(self, key, delta):
        """Сдвигает метрику в списке на delta позиций (-1 вверх, +1 вниз)."""
        i = self._order.index(key)
        j = i + delta
        if not (0 <= j < len(self._order)):
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._rebuild_list()

    def _on_save(self):
        """Сохраняет список отмеченных метрик в их порядке."""
        selected = [k for k in self._order if self._enabled[k]]
        if not selected:
            messagebox.showwarning("Настройки", "Оставьте хотя бы одну метрику.",
                                   parent=self)
            return
        self.result = list(selected)
        self.close()