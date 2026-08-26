"""
app.py — чистый старт с использованием вынесенного Оркестратора.
Спортсмены + Heatmap (год/неделя) + графики TP/Стресс во всю ширину.
Состояние (атлет, год, курсор недели, масштаб графиков) сохраняется
при закрытии и восстанавливается при старте (appsettings.py).
"""
import datetime
import os
import sys
import tkinter as tk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from theme import COL_BG_DARK, COL_TEXT_DIM
from ghost import ResizeController
from appsettings import AppSettings
from splash import SplashScreen
from orchestrator import AppOrchestrator  # ИМПОРТ ОРКЕСТРАТОРА

ATHLETES_COLUMN_FRACTION = 1 / 7
ATHLETES_COLUMN_MIN = 150

def handle_app_close(panel, orchestrator, root):
    """
    Реальная логика закрытия приложения.
    Вынесена отдельно, чтобы её можно было протестировать.
    """
    cur = panel.selected()
    # ⚠️ ЕСЛИ ВЫ ЗАКОММЕНТИРУЕТЕ ЭТУ СТРОКУ ЗДЕСЬ, ТЕСТ УПАДЕТ!
    orchestrator.save_state(current_athlete_id=cur[0] if cur else None)
    root.destroy()

if __name__ == "__main__":
    settings = AppSettings().load()

    root = tk.Tk()
    root.withdraw()
    # root.report_callback_exception = lambda *a: None
    root.title("Просмотр ЭКГ — анализ ВСР (вариабельность сердечного ритма)")
    root.geometry("1400x800")
    root.configure(bg=COL_BG_DARK)

    root.grid_columnconfigure(0, weight=0)
    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=0)

    splash = SplashScreen(root, show_ms=1800, auto_close=False)
    root.update()

    # --- загружаем тяжёлые модули с прогрессом ---
    def pump(fraction):
        splash.set_progress(fraction)
        root.update()

    pump(0.10)
    from database import get_db_path
    from models import get_session, Athlete, ECGRecord, ECGRaw
    pump(0.25)
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    pump(0.40)
    from sqlalchemy import func
    pump(0.50)
    import analysis
    from analysis import parse_rr, calc_metrics, calc_stress, stress_level
    pump(0.60)
    from atlets import AthletesPanel
    from heatmap import Heatmap
    from dialogs import ECGListDialog
    from charts import ChartsPanel, TP_METRIC, SI_METRIC
    pump(0.80)
    from importer import import_ecg
    pump(0.90)

    # ---------- левая колонка: спортсмены ----------
    panel = AthletesPanel(root)
    panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    panel.grid_propagate(False)

    # После изменения карточки атлета — перезагружаем данные графиков
    def _on_panel_changed():
        cur = panel.selected()
        orchestrator.sync_athlete(cur[0] if cur else None)
        hm.refresh()
        charts.refresh()
    panel.on_change = _on_panel_changed

    def _sync_athletes_width(event):
        if event.widget is root:
            w = max(ATHLETES_COLUMN_MIN, int(event.width * ATHLETES_COLUMN_FRACTION))
            panel.configure(width=w)

    root.bind("<Configure>", _sync_athletes_width)

    # ---------- статус-бар ----------
    status_var = tk.StringVar(value="Готово")
    status_bar = tk.Label(root, textvariable=status_var, bg=COL_BG_DARK,
                          fg=COL_TEXT_DIM, anchor="w", font=("Segoe UI", 10),
                          padx=10)
    status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    _status_timer = None

    def set_status(text, timeout=8000):
        global _status_timer
        status_var.set(text)
        if _status_timer:
            root.after_cancel(_status_timer)
        _status_timer = root.after(timeout, lambda: status_var.set("Готово"))

    # ---------- правая колонка ----------
    right = tk.Frame(root, bg=COL_BG_DARK)
    right.grid(row=0, column=1, sticky="nsew", padx=0, pady=10)

    # Вспомогательная функция для диалога ЭКГ
    def on_week_pick_action(day, block):
        if block is None:
            return
        cur = panel.selected()
        if not cur:
            return
        dt_from = datetime.datetime.combine(day, datetime.time(hour=block * 3))
        dt_to = dt_from + datetime.timedelta(hours=3)
        title = f"ЭКГ за {dt_from:%d.%m.%Y %H:%M}–{dt_to:%H:%M}"
        right.db_path = panel.db_path
        dlg = ECGListDialog(right, cur[0], dt_from, dt_to,
                            title, on_change=hm.refresh)

    # 1. Создаем виджеты (минимум колбэков здесь!)
    hm = Heatmap(right, on_pick=on_week_pick_action)
    charts = ChartsPanel(right, metrics=[TP_METRIC, SI_METRIC])
    
    # 2. Создаем Оркестратор и передаем ему виджеты
    orchestrator = AppOrchestrator(hm, charts, settings)
    
    # 3. ResizeController
    ResizeController(right, blocks=[hm, charts], gap=10)

    # ---------- импорт ----------
    def do_import():
        changed = import_ecg(root, panel.db_path, panel.athletes,
                              panel.selected(), set_status)
        if changed:
            panel.reload(select_id=changed)
            cur = panel.selected()
            orchestrator.sync_athlete(cur[0] if cur else None)
            hm.refresh()
            charts.refresh()

    panel.on_import = do_import

    # ---------- восстановление состояния ----------
    pump(0.95)

    saved_id = settings.get("athlete_id")
    panel.reload(select_id=saved_id)
    cur = panel.selected()
    
    # Устанавливаем обработчик ДО синхронизации
    panel.on_select = orchestrator.sync_athlete
    
    # Синхронизируем состояние
    orchestrator.sync_athlete(cur[0] if cur else None)
    
    # Восстанавливаем масштаб и позицию (год, неделя)
    orchestrator.restore_state(
        saved_athlete_id=cur[0] if cur else None,
        saved_year=settings.get("year"),
        saved_week=settings.get("week"),
        saved_zoom=settings.get("zoom")
    )
    
    # ⚡ ИСПРАВЛЕНИЕ: Явно вызываем refresh, чтобы гарантировать загрузку данных.
    # Это обходит любые "early returns" в сеттерах, которые могли сработать из-за 
    # порядка вызовов при инициализации, и делает запуск идентичным ручному переключению.
    hm.refresh()
    charts.refresh()
    
    root.update()
    
    # Восстанавливаем состояние heatmap и charts через оркестратор
    orchestrator.restore_state(
        saved_athlete_id=saved_id,
        saved_year=settings.get("year"),
        saved_week=settings.get("week"),
        saved_zoom=settings.get("zoom")
    )

    pump(1.0)
    root.update()
    splash.close_splash()
    root.deiconify()

    root.protocol("WM_DELETE_WINDOW", lambda: handle_app_close(panel, orchestrator, root))
    root.mainloop()