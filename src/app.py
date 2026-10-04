"""
app.py — чистый старт с использованием вынесенного Оркестратора.
Спортсмены + Heatmap (год/неделя) + графики TP/Стресс во всю ширину.
Состояние (атлет, год, курсор недели, масштаб графиков) сохраняется
при закрытии и восстанавливается при старте (appsettings.py).
"""
import locale

# Попытка установить русскую локаль
try:
    # Для Linux/Mac
    locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
except locale.Error:
    try:
        # Для Windows
        locale.setlocale(locale.LC_TIME, 'Russian_Russia.1251')
    except locale.Error:
        # Альтернатива для Windows
        locale.setlocale(locale.LC_TIME, 'ru_RU')

import datetime
import os
import sys
import threading
import tkinter as tk
import customtkinter as ctk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from theme import COL_BG_DARK, COL_TEXT_DIM
from ghost import ResizeController
from appsettings import AppSettings
from splash import SplashScreen
from orchestrator import AppOrchestrator
from app_constants import STATUS_TIMEOUT_MS

ATHLETES_COLUMN_FRACTION = 1 / 7
ATHLETES_COLUMN_MIN = 150

def handle_app_close(panel, orchestrator, root):
    cur = panel.selected()
    orchestrator.save_state(current_athlete_id=cur[0] if cur else None)
    root.destroy()
    sys.exit(0)    

if __name__ == "__main__":
    settings = AppSettings().load()

    root = tk.Tk()
    root.withdraw()
    root.title("Просмотр ЭКГ — анализ ВСР (вариабельность сердечного ритма)")
    root.geometry("1400x800")
    root.configure(bg=COL_BG_DARK)

    root.grid_columnconfigure(0, weight=0)
    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=0)

    splash = SplashScreen(root, show_ms=1800, auto_close=False)
    root.update()

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
    from dialogs import ECGJournal, HelpDialog, MetricsSettingsDialog
    from charts import (ChartsPanel, TP_METRIC, SI_METRIC, ALL_METRICS,
                        DEFAULT_METRIC_ORDER, metric_by_key)
    pump(0.80)
    from importer import import_ecg
    pump(0.90)

    # ---------- левая колонка: спортсмены ----------
    panel = AthletesPanel(root)
    panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    panel.grid_propagate(False)

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
    status_bar = tk.Frame(root, bg=COL_BG_DARK)
    status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
    status_bar.grid_columnconfigure(0, weight=1)
    tk.Label(status_bar, textvariable=status_var, bg=COL_BG_DARK,
             fg=COL_TEXT_DIM, anchor="w", font=("Segoe UI", 10),
             padx=10).grid(row=0, column=0, sticky="ew")

    def _open_metrics_settings():
        dlg = MetricsSettingsDialog(root, current_order=charts.metric_keys())
        dlg.modal_loop()
        # Только после подтверждения применяем и сохраняем.
        if dlg.result:
            specs = [metric_by_key(k) for k in dlg.result
                     if metric_by_key(k) is not None]
            charts.set_metrics(specs, db_path=panel.db_path)
            settings.set("metrics", dlg.result)
            settings.save()
            # Пересчитываем размер графиков под текущую ширину окна (после
            # пересоздания plots), чтобы пропорции не сбились.
            resize_ctrl.relayout()
            # Сбрасываем сохранённый зум: новые графики должны показать ВЕСЬ
            # диапазон данных, а не обрезанный кэш старого масштаба. Иначе при
            # смене метрик «на лету» часть данных не видна до перезапуска.
            orchestrator._saved_range = None
            # Восстанавливаем связи оркестратора и показываем данные текущего атлета.
            orchestrator.sync_athlete(orchestrator.heatmap.athlete)
            charts.refresh()

    btn_settings = ctk.CTkButton(status_bar, text="⚙ Настройки", width=110,
                                 height=24, command=_open_metrics_settings)
    btn_settings.grid(row=0, column=1, padx=(0, 8), pady=2)

    _status_timer = None

    def set_status(text, timeout=STATUS_TIMEOUT_MS, keep=False):
        global _status_timer
        status_var.set(text)
        if _status_timer:
            root.after_cancel(_status_timer)
            _status_timer = None
        if not keep:
            _status_timer = root.after(timeout, lambda: status_var.set("Готово"))

    # ---------- правая колонка ----------
    right = tk.Frame(root, bg=COL_BG_DARK)
    right.grid(row=0, column=1, sticky="nsew", padx=0, pady=10)

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
        dlg = ECGJournal(right, athlete_id=cur[0], date_from=dt_from, date_to=dt_to,
                         title=title, on_change=hm.refresh)

    hm = Heatmap(right, on_pick=on_week_pick_action)

    # --- метрики из настроек (порядок + состав) ---
    saved_metric_keys = settings.get("metrics")
    if saved_metric_keys:
        # Фильтруем только существующие ключи, сохраняя порядок.
        metric_specs = [metric_by_key(k) for k in saved_metric_keys
                        if metric_by_key(k) is not None]
    else:
        # На первый запуск — метрики по умолчанию.
        metric_specs = [metric_by_key(k) for k in DEFAULT_METRIC_ORDER
                        if metric_by_key(k) is not None]
    if not metric_specs:
        metric_specs = [TP_METRIC, SI_METRIC]   # безопасный фолбэк

    charts = ChartsPanel(right, metrics=metric_specs, db_path=panel.db_path)
    
    orchestrator = AppOrchestrator(hm, charts, settings)
    resize_ctrl = ResizeController(right, blocks=[hm, charts], gap=10)

    # Панель сама уведомляет оркестратор о выбранном атлете (в т.ч. при первом
    # reload ниже) — оркестратор наполняет heatmap и графики данными.
    panel.on_select = orchestrator.sync_athlete

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
    saved_year = settings.get("year")
    saved_week = settings.get("week")
    panel.reload(select_id=saved_id)
    cur = panel.selected()

    # На «первом запуске» (нет сохранённого года/недели) ставим карты на последнюю
    # запись атлета — иначе годовая карта показывает текущий год, а недельная пуста.
    if not saved_year and not saved_week and cur:
        last_dt = None
        session = get_session(panel.db_path)
        try:
            row = (session.query(ECGRecord.recorded_at)
                   .filter(ECGRecord.athlete_id == cur[0])
                   .order_by(ECGRecord.recorded_at.desc()).first())
            if row and row[0]:
                last_dt = datetime.datetime.fromisoformat(row[0]).date()
        except Exception:
            last_dt = None
        finally:
            session.close()
        if last_dt:
            hm.set_cursor_by_date(last_dt)

    orchestrator.restore_state(
        saved_athlete_id=cur[0] if cur else None,
        saved_year=saved_year,
        saved_week=saved_week,
        saved_zoom=settings.get("zoom")
    )
    
    hm.refresh()
    charts.refresh()
    root.update()
    
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

    # Фоновая генерация биометрических шаблонов для атлетов, у которых
    # достаточно записей (>= MIN_RECORDS), но шаблона ещё нет. Один поток,
    # по одному атлету за раз; прогресс отражается в строке статуса.
    # Отключается флагом auto_templates в app_settings.json.
    def _auto_templates():
        if settings.get("auto_templates", True) is False:
            return
        try:
            from ecg_biometrics import auto_build_all_templates
            auto_build_all_templates(panel.db_path, status_cb=set_status)
        except Exception:
            pass

    threading.Thread(target=_auto_templates, daemon=True).start()

    # F1 — инструкция пользователя
    def open_help(event=None):
        HelpDialog(root)
    root.bind("<F1>", open_help)

    root.protocol("WM_DELETE_WINDOW", lambda: handle_app_close(panel, orchestrator, root))
    root.mainloop()
    sys.exit(0)    