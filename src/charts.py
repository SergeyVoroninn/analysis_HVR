"""
charts.py — готовые параметры и общий контейнер графиков.
Отрисовка одного графика — в metricplot.py. Размер задаётся извне через
ResizeController (ghost.py): target_size / ghost_rects / apply_size.
"""
import tkinter as tk
import datetime as _dt

from analysis import stress_level
from theme import (COL_BG_DARK, COL_ONE, COL_WARN, COL_CRIT, COL_HIGH,
                   COL_ACCENT, COL_TP, COL_SI, COL_RMSSD, COL_HR)
from metricplot import MetricPlot, MetricSpec
from timeframe import get_chart_config
from database import get_db_path


def _si_color(v):
    return {"низкий": COL_ONE, "умеренный": COL_WARN,
            "высокий": COL_HIGH, "перенапряжение": COL_CRIT}.get(
        stress_level(v), COL_ONE)


# TP не может быть отрицательным, и у здоровых людей редко превышает 15000-20000 мс²
TP_METRIC = MetricSpec(
    "tp", "TP", "мс²",
    lambda r: r.tp if r.tp is not None else None,
    COL_TP,
    pid_floor=100.0,
    pid_ceiling=20000.0
)

# Индекс стресса (SI) не может быть отрицательным. Ограничим сверху разумным значением, 
# чтобы регулятор не предсказывал абсурдные 1000+ при резком скачке.
SI_METRIC = MetricSpec(
    "si", "Стресс", "ИС",
    lambda r: r.stress_si,
    _si_color,
    pid_floor=0.0,
    pid_ceiling=300.0,
    marker_color=COL_SI
)

# Частота сердечных сокращений (ЧСС) — уд/мин.
HR_METRIC = MetricSpec(
    "hr", "ЧСС", "уд/мин",
    lambda r: r.mean_hr if r.mean_hr is not None else None,
    COL_HR,
    pid_floor=30.0,
    pid_ceiling=220.0
)

# RMSSD — квадратный корень из среднего квадратов разностей соседних RR (мс).
RMSSD_METRIC = MetricSpec(
    "rmssd", "RMSSD", "мс",
    lambda r: r.rmssd if r.rmssd is not None else None,
    COL_RMSSD,
    pid_floor=5.0,
    pid_ceiling=200.0
)

# Полный каталог доступных метрик (ключ -> MetricSpec).
ALL_METRICS = {
    m.key: m for m in (TP_METRIC, SI_METRIC, HR_METRIC, RMSSD_METRIC)
}

# Порядок по умолчанию при первом запуске (если в настройках ничего нет).
DEFAULT_METRIC_ORDER = ["tp", "si", "hr", "rmssd"]


def metric_by_key(key):
    """Возвращает MetricSpec по ключу (или None)."""
    return ALL_METRICS.get(key)


class ChartsPanel(tk.Frame):
    """Общий контейнер графиков с вертикальной прокруткой.

    Высота каждого графика = ширина / ASPECT (фиксированное соотношение).
    Если все графики не помещаются в видимую область окна — появляется
    вертикальный скроллбар, позволяющий просмотреть остальные.
    """

    ASPECT = 6

    def __init__(self, master, metrics, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.db_path = db_path or get_db_path()
        self.current_athlete = None          # последний выставленный атлет
        self.on_range_changed = None  # callback(lo, hi) для оркестратора

        # Прокручиваемый канвас: графики живут внутри self._container.
        # Используем place-менеджер, чтобы канвас всегда занимал весь фрейм
        # (pack конфликтовал с внешним place, ужимал канвас до размера контента).
        # Скроллбар скрыт: прокрутка только колесом мыши.
        self._canvas = tk.Canvas(self, bg=COL_BG_DARK, highlightthickness=0)
        self._canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._container = tk.Frame(self._canvas, bg=COL_BG_DARK)
        self._window = self._canvas.create_window(
            (0, 0), window=self._container, anchor="nw")
        self._container.bind("<Configure>", self._on_container_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # Колесо на пустой области контейнера — тоже прокрутка. На самих
        # графиках колесо обрабатывает MetricPlot (скролл через on_scroll_vertical),
        # поэтому на контейнере/канвасе дублирующий бинд не нужен, иначе
        # прокрутка срабатывала бы дважды за щелчок колеса.
        self._container.bind("<MouseWheel>", self._on_wheel, add="+")

        self._plots = []
        self._build_plots(metrics)

    def _on_wheel(self, steps=None):
        """Прокручивает панель графиков по вертикали (колесо мыши).

        Принимает либо число steps (из MetricPlot.on_scroll_vertical), либо
        Tk-событие <MouseWheel> (event.delta) с канваса.

        Если все графики уже помещаются во фрейм (прокрутка не нужна) — ничего
        не делает, чтобы колесо не «гоняло пустое место» туда-сюда.
        """
        try:
            if hasattr(steps, "delta"):       # Tk-событие
                steps = 1 if steps.delta > 0 else -1
            if steps is None:
                return
            if not self._can_scroll():
                return
            self._canvas.yview_scroll(-steps * 3, "units")
        except Exception:
            pass

    def _can_scroll(self):
        """Есть ли что прокручивать: контент выше видимой области канваса."""
        try:
            content = self._container.winfo_height()
            visible = self._canvas.winfo_height()
            return content > visible + 2
        except Exception:
            return False

    def _on_container_configure(self, event=None):
        # Ширина содержимого = ширине видимой области канваса.
        try:
            self._canvas.itemconfigure(self._window, width=self._canvas.winfo_width())
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas_configure(self, event=None):
        self._canvas.itemconfigure(self._window, width=event.width)

    def _build_plots(self, specs):
        """Создаёт MetricPlot-ы из списка MetricSpec (первый раз или при set_metrics)."""
        for p in self._plots:
            try:
                p.destroy()
            except Exception:
                pass
        self._plots = [MetricPlot(self._container, m, db_path=self.db_path)
                       for m in specs]
        for p in self._plots:
            p.on_view_changed = self._apply_zoom
            p.on_scroll_vertical = self._on_wheel
            p.pack(side="top", fill="x", pady=0)
            p.athlete = self.current_athlete
        self._rebind_public_callbacks()
        self._on_container_configure()

    def metric_keys(self):
        """Ключи метрик в текущем порядке отображения."""
        return [p.spec.key for p in self._plots]

    def set_metrics(self, specs, db_path=None):
        """Полностью пересоздаёт графики по новому списку MetricSpec (состав+порядок)."""
        if db_path:
            self.db_path = db_path
        self._build_plots(specs)

    # Колбэки оркестратора переназначаются при каждом пересоздании графиков.
    def _rebind_public_callbacks(self):
        for p in self._plots:
            p.on_year_pick = getattr(self, "_year_pick_cb", None)
            p.on_reset = getattr(self, "_reset_cb", None)
            p.on_single_click = getattr(self, "_single_click_cb", None)
            p.on_view_changed = self._apply_zoom

    def _apply_zoom(self, view):
        if getattr(self, '_is_updating_view', False):
            return
        self._is_updating_view = True
        
        for p in self._plots:
            p.view = view
        
        v = None
        if self._plots:
            p0 = self._plots[0]
            v = p0._view_ordinals()
            if v is not None:
                lo, hi = v
                vspan = max(1, hi - lo)
                if vspan <= p0.SMALL_SPAN:
                    config = get_chart_config(vspan)
                    forced_tf = config.bar_tf
                else:
                    forced_tf = None
                for p in self._plots:
                    p.set_forced_tf(forced_tf)
        
        for p in self._plots:
            p.redraw()
        
        self._is_updating_view = False
        
        if self.on_range_changed and v is not None:
            self.on_range_changed(lo, hi)

    def set_year_pick_callback(self, cb):
        self._year_pick_cb = cb
        for p in self._plots:
            p.on_year_pick = cb

    def set_reset_callback(self, cb):
        self._reset_cb = cb
        for p in self._plots:
            p.on_reset = cb

    def set_single_click_callback(self, cb):
        self._single_click_cb = cb
        for p in self._plots:
            p.on_single_click = cb

    # ---------------- хуки ghost-ресайза ----------------
    def ghost_shown(self):
        for p in self._plots:
            p.set_frozen(True)

    def ghost_hidden(self):
        for p in self._plots:
            p.set_frozen(False)

    def _each_height(self, avail_w, avail_h=None):
        """Высота ОДНОЙ строки графика: фиксированное соотношение w/ASPECT.

        Не зависит от высоты окна — если графики не помещаются, их можно
        прокрутить вертикальным скроллбаром.
        """
        return max(120, int(avail_w / self.ASPECT))

    def target_size(self, avail_w, avail_h=None):
        h_each = self._each_height(avail_w, avail_h)
        return avail_w, len(self._plots) * h_each

    def ghost_rects(self, w, h):
        h_each = self._each_height(w, h)
        rects, y = [], 0
        for _ in self._plots:
            rects.append((1, y + 2, w - 1, y + 2 + h_each))
            y += h_each + 4
        return rects

    def apply_size(self, w, h):
        # Каждый график получает фиксированную высоту w/ASPECT; суммарная
        # желаемая высота больше видимой — остальное закрыто скроллбаром.
        h_each = self._each_height(w, h)
        for p in self._plots:
            p.set_size(w, h_each)

    # ---------------- входы ----------------
    @property
    def athlete(self):
        return self._plots[0].athlete if self._plots else None

    @athlete.setter
    def athlete(self, aid):
        self.current_athlete = aid
        for p in self._plots:
            p.athlete = aid

    def set_range(self, start, end):
        for p in self._plots:
            p.set_range(start, end)

    # ---------------- общий масштаб по X ----------------
    @property
    def zoom(self):
        """Абсолютное окно (lo, hi) в ординалах или None."""
        return self._plots[0].view if self._plots else None

    @zoom.setter
    def zoom(self, view):
        """Установить масштаб без лишней перезагрузки данных."""
        self._apply_zoom(view)

    def redraw(self):
        for p in self._plots:
            p.redraw()

    def refresh(self):
        """Принудительная перезагрузка данных графиков (после импорта)."""
        for p in self._plots:
            p._reload()

    def center_on_week(self, week_start_date):
        """Центрировать графики по среде выбранной недели."""
        if self._plots:
            self._plots[0].center_on_week(week_start_date)

    def zoom_to_week(self, week_start_date):
        """Диапазон графиков = кликнутая неделя (пн–вс)."""
        if not self._plots:
            return
        p0 = self._plots[0]
        if p0._start is None:
            return
        
        monday = week_start_date
        sunday = monday + _dt.timedelta(days=6)
        lo = p0._ord(monday)
        hi = p0._ord(sunday) + 1
        
        self._apply_zoom((lo, hi))