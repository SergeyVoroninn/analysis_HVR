"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).

Режимы масштаба:
  span < 7 дней     — фиксация на WEEK (минимальный масштаб)
  7 <= span <= 30   — HOUR3 (3 часа), зебра DAY
  30 < span <= 365  — DAY (день), зебра WEEK, подписи месяц
  span > 365        — пропорциональная цена бара, подписи годы

Управление:
  колесо       — зум к курсору (внутри стоп на 3часа);
  зажать и тянуть — панорамирование;
  ПКМ          — сброс на весь период;
  двойной клик — зум до года кликнутого столбика.
"""
import datetime
import time as _time
import tkinter as tk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_TEXT_DIM,
                   COL_SPINE, COL_TP_YEAR)
from timeframe import TimeFrame, get_chart_config, calc_proportional_bar_size, pick_year_step


class _FrozenCanvas(FigureCanvasTkAgg):
    """Канвас, который не перерисовывается, пока заморожен (ресайз окна)."""

    def __init__(self, figure, master=None):
        super().__init__(figure, master=master)
        self._frozen = False

    def resize(self, event):
        if self._frozen:
            return
        super().resize(event)

    def set_frozen(self, frozen):
        self._frozen = frozen


class MetricSpec:
    def __init__(self, key, name, ylabel, value, color=None):
        self.key = key
        self.name = name
        self.ylabel = ylabel
        self.value = value
        self.color = color


class MetricPlot(tk.Frame):

    SMALL_SPAN = 365            # до года — календарные бары
    TARGET_BAR_PX = 15          # целевая ширина бара в пропорц. режиме

    def __init__(self, master, spec, db_path=None):
        super().__init__(master, bg=COL_BG_DARK)
        self.spec = spec
        self.db_path = db_path or get_db_path()
        self._athlete = None
        self._start = None
        self._end = None
        self._values = []
        self.view = None
        self._pan = None
        self._load_seq = 0          # порядковый номер загрузки (отсев устаревших)
        self._loading = False       # идёт фоновая загрузка
        self._single_timer = None
        self._click_t = 0.0
        self._click_x = 0.0
        self._click_y = 0.0
        self._current_tf = None
        self._forced_tf = None
        self.on_view_changed = None
        self.on_year_pick = None
        self.on_reset = None
        self.on_single_click = None

        self.fig = Figure(dpi=100)
        self.fig.patch.set_facecolor(COL_BG_DARK)
        self.ax = self.fig.add_subplot(111)
        self.canvas = _FrozenCanvas(self.fig, master=self)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(background=COL_BG_WIDGET)
        self.widget.pack(side="top", fill="x")
        self.fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.18)
        self._style()

        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

    def set_frozen(self, frozen):
        self.canvas.set_frozen(frozen)

    # ---------------- входы ----------------
    @property
    def athlete(self):
        return self._athlete

    @athlete.setter
    def athlete(self, aid):
        self._athlete = aid
        self._start = self._end = None
        self._current_tf = None
        self._reload()

    def set_range(self, start, end):
        self._start, self._end = start, end
        self.view = None
        self._current_tf = None
        self._reload()

    def set_size(self, w, h):
        self.widget.configure(width=w, height=h)

    def set_forced_tf(self, tf):
        """Установить таймфрейм принудительно (из ChartsPanel)."""
        self._forced_tf = tf

    def redraw(self):
        self._draw()

    # ---------------- данные ----------------
    def _reload(self, async_load=True):
        self._values = []
        if not self._athlete:
            self._draw()
            return
        if async_load:
            self._start_background_load()
            return
        self._load_sync()

    def _load_sync(self):
        """Синхронная загрузка данных из БД (используется в фоновом потоке)."""
        self._values = []
        if not self._athlete:
            return
        session = get_session(self.db_path)
        try:
            q = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == self._athlete)
            if self._start:
                q = q.filter(ECGRecord.recorded_at >=
                             self._start.isoformat() + " 00:00:00")
            if self._end:
                q = q.filter(ECGRecord.recorded_at <
                             self._end.isoformat() + " 23:59:59")
            for rec in q.all():
                v = self.spec.value(rec)
                if v is not None:
                    self._values.append(
                        (datetime.datetime.fromisoformat(rec.recorded_at), v))
        finally:
            session.close()

        if self._start is None and self._values:
            self._start = min(d for d, _ in self._values).date()
            self._end = max(d for d, _ in self._values).date()

    def _start_background_load(self):
        """Запускает загрузку данных в фоновом потоке, отсеивая устаревшие."""
        self._load_seq += 1
        seq = self._load_seq
        athlete = self._athlete
        self._loading = True

        def worker():
            try:
                values = self._fetch_values(athlete)
            except Exception:
                values = []
            try:
                self.after(0, lambda: self._apply_background_load(seq, athlete, values))
            except RuntimeError:
                pass  # Tk уже разрушен — результат не нужен

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _fetch_values(self, athlete):
        """Тяжёлый SQL-запрос — выполняется в фоновом потоке."""
        if not athlete:
            return []
        session = get_session(self.db_path)
        try:
            q = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == athlete)
            if self._start:
                q = q.filter(ECGRecord.recorded_at >=
                             self._start.isoformat() + " 00:00:00")
            if self._end:
                q = q.filter(ECGRecord.recorded_at <
                             self._end.isoformat() + " 23:59:59")
            out = []
            for rec in q.all():
                v = self.spec.value(rec)
                if v is not None:
                    out.append((datetime.datetime.fromisoformat(rec.recorded_at), v))
            return out
        finally:
            session.close()

    def _apply_background_load(self, seq, athlete, values):
        """Применяет результат загрузки, если за это время не сменили атлета."""
        if seq != self._load_seq or athlete != self._athlete:
            return  # устаревший результат — игнорируем
        self._values = values
        if self._start is None and self._values:
            self._start = min(d for d, _ in self._values).date()
            self._end = max(d for d, _ in self._values).date()
        self._loading = False
        self._draw()

    # ---------------- ординалы и view ----------------
    def _ord(self, x):
        if isinstance(x, datetime.datetime):
            return x.date().toordinal() + x.hour / 24.0 + x.minute / 1440.0
        if isinstance(x, datetime.date):
            return x.toordinal()
        return float(x)

    def _view_ordinals(self):
        if self.view is not None:
            lo, hi = self.view
            if lo >= 1 and hi > lo:
                return float(lo), float(hi)
        if self._start is None:
            return None
        return float(self._ord(self._start)), float(self._ord(self._end)) + 1

    def _commit_view(self, lo, hi):
        if lo is None or hi is None:
            self.view = None
        else:
            self.view = (float(lo), float(hi))
        
        if self.on_view_changed:
            self.on_view_changed(self.view)
        else:
            self._draw()

    # ---------------- зум / панорама ----------------
    def _on_scroll(self, event):
        if event.xdata is None or self._start is None:
            return
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        factor = 0.85 if event.button == "up" else 1.18
        width_px = max(100, self.ax.get_window_extent().width)
        # Минимальный span = 1 день
        min_span = 1.0
        new_span = min(365000, max(min_span, (hi - lo) * factor))
        ratio = (event.xdata - lo) / max(1e-9, hi - lo)
        new_lo = event.xdata - ratio * new_span
        new_hi = new_lo + new_span
        self._commit_view(new_lo, new_hi)

    def _on_press(self, event):
        if event.button == 3:
            self._current_tf = None
            if self.on_reset:
                self.on_reset()
            return
            
        if event.button != 1 or event.xdata is None or self._start is None:
            return

        now = _time.monotonic()
        is_dbl = (now - self._click_t < 0.45 and
                  abs(event.x - self._click_x) < 6 and
                  abs(event.y - self._click_y) < 6)
        self._click_t = now
        self._click_x = event.x
        self._click_y = event.y

        if is_dbl:
            # двойной клик игнорируется — не эргономично
            return

        if self.on_single_click:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
            d = datetime.date.fromordinal(int(event.xdata))
            self._single_timer = self.after(
                500, lambda dd=d: self._fire_single(dd))

        v = self._view_ordinals()
        if v is None:
            return
        self._pan = (event.x, v[0], v[1])

    def _fire_single(self, d):
        self._single_timer = None
        if self.on_single_click:
            self.on_single_click(d)

    def _on_motion(self, event):
        if self._pan is None or event.button != 1:
            return
        x0, lo0, hi0 = self._pan
        width_px = self.ax.get_window_extent().width
        if width_px <= 1:
            return
        span = hi0 - lo0
        shift = (x0 - event.x) * span / width_px
        self._commit_view(lo0 + shift, lo0 + shift + span)

    def _on_release(self, event):
        self._pan = None

    def center_on_week(self, week_start_date):
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        span = hi - lo
        center = self._ord(week_start_date + datetime.timedelta(days=3))
        self._commit_view(center - span / 2, center + span / 2)

    # ---------------- отрисовка ----------------
    def _style(self):
        self.ax.set_facecolor(COL_BG_DARK)
        self.ax.tick_params(colors=COL_TEXT_LIGHT, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(COL_SPINE)

    def _draw(self):
        ax = self.ax
        ax.clear()
        self._style()

        if not self._values or not self._start:
            ax.set_title(f"{self.spec.name}: нет данных",
                         color=COL_TEXT_DIM, fontsize=9)
            self.canvas.draw_idle()
            return

        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        vspan = max(1, hi - lo)
        width_px = max(100, self.ax.get_window_extent().width)

        # Получаем конфигурацию отрисовки из timeframe.py
        config = get_chart_config(vspan)
        
        if config.is_proportional:
            # Пропорциональный режим (span > 365)
            bar_size = calc_proportional_bar_size(vspan, width_px, self.TARGET_BAR_PX)
            bw = bar_size * 0.95
            def key(x): return int(x / bar_size) * bar_size
            self._shade_years(ax, lo, hi, pick_year_step(vspan))
            self._set_year_ticks(ax, lo, hi)
            tf_label = f"{bar_size / 365:.1f}г" if bar_size >= 365 else f"{bar_size:.0f}д"
        else:
            # Календарный режим
            tf = config.bar_tf
            self._current_tf = tf
            bw = tf.bar_size * 0.95
            def key(x): return tf.bin_key(x)
            self._shade_tf(ax, lo, hi, config.zebra_tf)
            self._set_x_ticks_small(ax, lo, hi, vspan, config)
            tf_label = tf.label

        # Фильтруем данные для текущего view
        view_values = [(dt, vv) for dt, vv in self._values 
                       if lo <= self._ord(dt) < hi]

        # Агрегируем данные
        agg = {}
        for dt, vv in view_values:
            x = self._ord(dt)
            agg.setdefault(key(x), []).append(vv)
        
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs] if xs else []

        # Рисуем бары
        if xs and ys:
            c = self.spec.color
            colors = [c(vv) for vv in ys] if callable(c) else (c or COL_TP_YEAR)
            ax.bar(xs, ys, width=bw, color=colors, align="edge", zorder=2)

        ax.set_xlim(lo, hi)
        if ys:
            ax.set_ylim(0, (max(ys) or 1) * 1.1)
        else:
            ax.set_ylim(0, 1)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)

        d0 = datetime.date.fromordinal(max(1, int(lo)))
        d1 = datetime.date.fromordinal(max(1, int(hi)))
        range_str = f"{d0:%d.%m.%y}–{d1:%d.%m.%y}"
        ax.set_title(f"{self.spec.name} | {tf_label} ({range_str})",
                     color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    # ---------------- ось X ----------------
    def _set_x_ticks_small(self, ax, lo, hi, vspan, config):
        """Установка подписей оси X на основе конфигурации."""
        ticks, names = [], []
        
        # Русские названия месяцев
        months_ru = ["янв", "фев", "мар", "апр", "май", "июн",
                     "июл", "авг", "сен", "окт", "ноя", "дек"]
        
        # Русские сокращения дней недели
        weekdays_ru = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
        
        # Недельный диапазон (1.5 < vspan <= 7): дата в понедельник, дни недели для остальных
        if 1.5 < vspan <= 7:
            d0 = datetime.date.fromordinal(max(1, int(lo)))
            d1 = datetime.date.fromordinal(max(1, int(hi)))
            
            # Проходим по каждому дню в диапазоне
            current = d0
            while current <= d1:
                ticks.append(current.toordinal())
                # Понедельник (weekday() == 0) — показываем дату, остальные — день недели
                if current.weekday() == 0:
                    names.append(current.strftime("%d.%m"))
                else:
                    names.append(weekdays_ru[current.weekday()])
                current += datetime.timedelta(days=1)
        
        # Суточный диапазон (<= 1.5 дня): подписи каждые 3 часа, начиная с 00:00
        elif vspan <= 1.5:
            start_date = datetime.date.fromordinal(max(1, int(lo)))
            
            # Создаем datetime на 00:00 этого дня
            current = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
            
            # Генерируем подписи каждые 3 часа
            while self._ord(current) <= hi + 0.5:
                if current.hour == 0:
                    label = current.strftime("%d.%m")
                else:
                    label = current.strftime("%H:%M")
                
                ticks.append(self._ord(current))
                names.append(label)
                current += datetime.timedelta(hours=3)
        
        elif config.tick_format == "3hour" and config.tick_step_hours > 0:
            # Месячный диапазон с подписями каждые N часов
            start_date = datetime.date.fromordinal(max(1, int(lo)))
            
            # Создаем datetime на 00:00
            current = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
            
            step = datetime.timedelta(hours=config.tick_step_hours)
            
            while self._ord(current) <= hi + 0.5:
                if current.hour == 0:
                    label = current.strftime("%d.%m")
                else:
                    label = current.strftime("%H:%M")
                
                ticks.append(self._ord(current))
                names.append(label)
                current += step
        
        elif config.bar_tf is TimeFrame.DAY and vspan > 31:
            # Годовой диапазон: подписи по 1-му числу каждого месяца
            d0 = datetime.date.fromordinal(max(1, int(lo)))
            d1 = datetime.date.fromordinal(max(1, int(hi)))
            
            current = d0.replace(day=1)
            if current < d0:
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
            
            while current <= d1:
                ticks.append(current.toordinal())
                names.append(months_ru[current.month - 1])
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
        
        elif config.bar_tf is TimeFrame.HOUR3 and vspan <= 31:
            # Месячный диапазон: подписи по понедельникам
            d0 = datetime.date.fromordinal(max(1, int(lo)))
            d1 = datetime.date.fromordinal(max(1, int(hi)))
            
            current = d0 - datetime.timedelta(days=d0.weekday())
            if current < d0:
                current += datetime.timedelta(days=7)
            
            while current <= d1:
                ticks.append(current.toordinal())
                names.append(current.strftime("%d.%m"))
                current += datetime.timedelta(days=7)
        
        else:
            # Для других диапазонов: используем zebra_tf
            bounds = list(self._sibling_bounds(config.zebra_tf, lo, hi))
            last_tick_ord = -999
            
            for d in bounds:
                d_ord = self._ord(d)
                if d_ord - last_tick_ord < config.tick_step_days:
                    continue
                
                label = d.strftime(config.tick_format)
                ticks.append(d_ord)
                names.append(label)
                last_tick_ord = d_ord
        
        ax.set_xticks(ticks)
        ax.set_xticklabels(names, fontsize=7)

    def _set_year_ticks(self, ax, lo, hi):
        n = pick_year_step(max(1, hi - lo))
        d0 = datetime.date.fromordinal(max(1, int(lo)))
        d1 = datetime.date.fromordinal(max(1, int(hi)))
        y = max(1, (d0.year // n) * n)
        ticks, names = [], []
        while y <= d1.year:
            x = datetime.date(y, 1, 1).toordinal()
            if lo - 1e-9 <= x <= hi:
                ticks.append(x)
                names.append(str(y))
            y += n
        ax.set_xticks(ticks)
        ax.set_xticklabels(names, fontsize=7)

    def _sibling_bounds(self, sib, lo, hi):
        """Генератор границ для зебры и подписей оси X."""
        d0 = datetime.date.fromordinal(max(1, int(lo)))
        
        if sib in (TimeFrame.HOUR1, TimeFrame.HOUR3):
            d0 = datetime.datetime.combine(d0, datetime.time())
            if sib is TimeFrame.HOUR1:
                d = d0.replace(minute=0, second=0, microsecond=0)
            else:
                d = d0.replace(hour=(d0.hour // 3) * 3, minute=0, second=0)
        elif sib is TimeFrame.DAY:
            d = d0
        elif sib is TimeFrame.WEEK:
            d = d0 - datetime.timedelta(days=d0.weekday())
        else:
            d = d0
        
        while self._ord(d) <= hi:
            if self._ord(d) >= lo - 1e-9:
                yield d
            d = self._next_bound(sib, d)

    @staticmethod
    def _next_bound(sib, d):
        """Следующая граница для данного таймфрейма."""
        if sib is TimeFrame.HOUR1:  # НОВОЕ
            return d + datetime.timedelta(hours=1)
        if sib is TimeFrame.HOUR3:
            return d + datetime.timedelta(hours=3)
        if sib is TimeFrame.DAY:
            return d + datetime.timedelta(days=1)
        if sib is TimeFrame.WEEK:
            return d + datetime.timedelta(days=7)
        return d + datetime.timedelta(days=1)

    # ---------------- зебра ----------------
    def _shade_tf(self, ax, lo, hi, sib):
        step = sib.bar_size
        if step <= 0:
            return
        x = sib.bin_key(lo) - step
        while x <= hi:
            x0, x1 = x, x + step
            if int(round(x0 / step)) % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            x = x1

    def _shade_years(self, ax, lo, hi, n):
        d0 = datetime.date.fromordinal(max(1, int(lo)))
        y = (d0.year // n) * n - n
        while y <= 9999:
            x0 = datetime.date(max(1, y), 1, 1).toordinal()
            if x0 > hi:
                break
            x1 = datetime.date(min(9999, y + n), 1, 1).toordinal()
            if (y // n) % 2:
                ax.axvspan(max(x0, lo), min(x1, hi),
                           color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
            if lo < x0 < hi:
                ax.axvline(x0, color=COL_TEXT_DIM,
                           linewidth=0.6, alpha=0.35, zorder=0)
            y += n

    @staticmethod
    def _tick_label(sib, d, vspan):
        """Формат подписи для оси X."""
        if sib is TimeFrame.HOUR1:  # НОВОЕ
            return d.strftime("%H:%M") if vspan <= 2 else d.strftime("%d.%m %H:%M")
        if sib is TimeFrame.HOUR3:
            return d.strftime("%H:%M") if vspan <= 7 else d.strftime("%d.%m %H:%M")
        if sib is TimeFrame.DAY:
            if vspan > 300:
                return d.strftime("%b") if d.day == 1 else ""
            return d.strftime("%d.%m.%y") if vspan > 350 else d.strftime("%d.%m")
        if sib is TimeFrame.WEEK:
            return d.strftime("%d.%m.%y") if vspan > 350 else d.strftime("%d.%m")
        return d.strftime("%d.%m")