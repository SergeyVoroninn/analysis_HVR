"""Диалог биометрической верификации при импорте."""
import tkinter as tk

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_WARN, COL_ONE, COL_CRIT,
                   COL_ACCENT, COL_SELECTION)
from ecg_biometrics import cfg


class BiometricChoiceDialog(tk.Toplevel):
    """Окно выбора при биометрическом несовпадении записи ЭКГ с текущим атлетом."""

    def __init__(self, parent, current_name, current_prob, best_name, best_prob,
                 is_relative=False, best_records=0):
        super().__init__(parent)
        self.title("🔍 Биометрическая верификация")
        self.geometry("550x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.protocol("WM_DELETE_WINDOW", lambda: self._close("cancel"))

        self.configure(bg=COL_BG_DARK)

        tk.Label(self, text="Обнаружено расхождение биометрических данных",
                 font=("Segoe UI", 12, "bold"), bg=COL_BG_DARK, fg=COL_TEXT_LIGHT).pack(pady=10)

        tk.Label(self, text="Если ни один из вариантов не подходит, выберите отмену импорта.",
                 font=("Segoe UI", 9), bg=COL_BG_DARK, fg=COL_WARN).pack(pady=(0, 10))

        cur_frame = tk.Frame(self, bg=COL_ACCENT, padx=15, pady=10)
        cur_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(cur_frame, text=f"👤 Текущий выбор:", font=("Segoe UI", 10), bg=COL_ACCENT, fg=COL_TEXT_LIGHT).pack(anchor="w")
        tk.Label(cur_frame, text=current_name, font=("Segoe UI", 11, "bold"), bg=COL_ACCENT, fg=COL_SELECTION).pack(anchor="w")
        tk.Label(cur_frame, text=f"Совпадение: {current_prob:.1f}%", font=("Segoe UI", 10), bg=COL_ACCENT, fg=COL_WARN).pack(anchor="w")

        best_frame = tk.Frame(self, bg=COL_ONE, padx=15, pady=10)
        best_frame.pack(fill="x", padx=20, pady=5)

        relative_marker = " 👥 (возможно, родственник)" if is_relative else ""
        tk.Label(best_frame, text=f"🎯 Найдено лучшее совпадение{relative_marker}:",
                 font=("Segoe UI", 10), bg=COL_ONE, fg=COL_TEXT_LIGHT).pack(anchor="w")
        tk.Label(best_frame, text=best_name, font=("Segoe UI", 11, "bold"), bg=COL_ONE, fg=COL_SELECTION).pack(anchor="w")

        reliability_text = ""
        if best_records < cfg.RELIABILITY_LOW_THRESH:
            reliability_text = f" ⚠️ (Шаблон ненадежен: всего {best_records} записей)"
            prob_color = COL_CRIT
        elif best_records < cfg.RELIABILITY_HIGH_THRESH:
            reliability_text = f" (Шаблон формируется: {best_records} записей)"
            prob_color = COL_SELECTION
        else:
            reliability_text = f" (Надежный шаблон: {best_records} записей)"
            prob_color = COL_SELECTION

        tk.Label(best_frame, text=f"Совпадение: {best_prob:.1f}%{reliability_text}",
                 font=("Segoe UI", 10, "bold"), bg=COL_ONE, fg=prob_color).pack(anchor="w")

        btn_frame = tk.Frame(self, bg=COL_BG_DARK)
        btn_frame.pack(fill="x", padx=20, pady=15)

        tk.Button(btn_frame, text=f"✅ Привязать к: {best_name.split()[0]}",
                  command=lambda: self._close("best"), bg=COL_ONE, fg=COL_SELECTION,
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text=f"✓ Оставить у текущего: {current_name.split()[0]}",
                  command=lambda: self._close("current"), bg=COL_ACCENT, fg=COL_SELECTION,
                  font=("Segoe UI", 10), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text="❌ Ни один не подходит (Отменить импорт)",
                  command=lambda: self._close("cancel"), bg=COL_CRIT, fg=COL_SELECTION,
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        self.bind("<Escape>", lambda e: self._close("cancel"))
        self.focus_force()

    def _close(self, result):
        self.result = result
        self.destroy()