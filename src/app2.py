"""
app2.py — чистый старт.
Спортсмены + Heatmap (год/неделя) + графики TP/Стресс во всю ширину.
Состояние (атлет, год, курсор недели, масштаб графиков) сохраняется
при закрытии и восстанавливается при старте (appsettings.py).
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
from charts import ChartsPanel, TP_METRIC, SI_METRIC
from ghost import ResizeController
from appsettings import AppSettings

# Доля ширины окна, отводимая колонке «Спортсмены» (1/7 ≈ 0.143).
ATHLETES_COLUMN_FRACTION = 1 / 7
ATHLETES_COLUMN_MIN = 150          # px — минимум, чтобы колонка не схлопнулась

if __name__ == "__main__":
    settings = AppSettings().load()

    root = tk.Tk()
    root.title("Просмотр ЭКГ — анализ ВСР (вариабельность сердечного ритма)")
    root.geometry("1400x800")
    root.configure(bg=COL_BG_DARK)

    root.grid_columnconfigure(0, weight=0)
    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(0, weight=1)

    # ---------- левая колонка: спортсмены ----------
    panel = AthletesPanel(root)
    panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    panel.grid_propagate(False)

    def _sync_athletes_width(event):
        if event.widget is root:
            w = max(ATHLETES_COLUMN_MIN, int(event.width * ATHLETES_COLUMN_FRACTION))
            panel.configure(width=w)

    root.bind("<Configure>", _sync_athletes_width)

    # ---------- правая колонка ----------
    right = tk.Frame(root, bg=COL_BG_DARK)
    right.grid(row=0, column=1, sticky="nsew", padx=0, pady=10)

    hm = Heatmap(right,
                 on_week_pick=lambda w, d: charts.center_on_week(d),
                 on_pick=lambda day, b: print("🕒", day, "блок", b))
    charts = ChartsPanel(right, metrics=[TP_METRIC, SI_METRIC])
    charts.set_year_pick_callback(hm.set_year)
    charts.set_reset_callback(hm.reset_to_data_center)
    charts.set_single_click_callback(hm.set_cursor_by_date)

    # размеры и позиции блоков считает и применяет контроллер (одно место)
    ResizeController(right, blocks=[hm, charts], gap=10)

    def on_select(aid):
        hm.athlete = aid
        charts.athlete = aid

    # ---------- восстановление состояния ----------
    saved_id = settings.get("athlete_id")
    panel.reload(select_id=saved_id)      # сохранённый или первый, если его нет
    panel.on_select = on_select
    cur = panel.selected()
    on_select(cur[0] if cur else None)
    root.update()                      # дать yearmap загрузить данные

    hm.set_selection(year=settings.get("year"), week=settings.get("week"))

    saved_zoom = settings.get("zoom")
    if saved_zoom and len(saved_zoom) == 2 and saved_zoom[0] and saved_zoom[1]:
        charts.zoom = tuple(saved_zoom)
        charts.redraw()

    # ---------- сохранение при закрытии ----------
    def on_close():
        cur = panel.selected()
        settings.set("athlete_id", cur[0] if cur else None)
        settings.set("year", hm.year)
        settings.set("week", hm.week)
        z = charts.zoom
        settings.set("zoom", list(z) if z else None)
        settings.save()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()
