"""
app2.py — чистый старт.
Спортсмены + Heatmap (год/неделя) + график TP во всю ширину.
"""
import os
import sys
import tkinter as tk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from theme import COL_BG_DARK
from atlets import AthletesPanel
from heatmap import Heatmap
from charts import ChartsPanel, TP_METRIC

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Просмотр ЭКГ — анализ ВСР (вариабельность сердечного ритма)")
    root.geometry("1400x800")
    root.configure(bg=COL_BG_DARK)

    root.grid_columnconfigure(0, weight=1, minsize=250)
    root.grid_columnconfigure(1, weight=3)
    root.grid_rowconfigure(0, weight=1)

    # ---------- левая колонка: спортсмены ----------
    panel = AthletesPanel(root)
    panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # ---------- правая колонка ----------
    right = tk.Frame(root, bg=COL_BG_DARK)
    right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
    right.grid_columnconfigure(0, weight=1)
    # weight у строк НЕ ставим: блоки идут сверху вниз, лишнее место внизу

    hm = Heatmap(right,
                 on_pick=lambda day, b: print("🕒", day, "блок", b))
    hm.grid(row=1, column=0, sticky="new")

    charts = ChartsPanel(right, metrics=[TP_METRIC])
    charts.grid(row=2, column=0, sticky="new", pady=(10, 0))

    def on_select(aid):
        hm.athlete = aid
        charts.athlete = aid

    panel.on_select = on_select

    root.mainloop()