"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).
"""
import datetime
import time as _time
import tkinter as tk
import bisect

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database import get_db_path
from models import get_session, ECGRecord
from theme import (COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_TEXT_DIM,
                   COL_SPINE, COL_TP_YEAR)
from timeframe import TimeFrame, get_chart_config, calc_proportional_bar_size, pick_year_step
from timeframe import WEEKDAYS_RU, MONTHS_RU  # Импортируем константы локализации
from analyzer import MetricAnalyzer


class _FrozenCanvas(FigureCanvasTkAgg):
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
    SMALL_SPAN = 365
    TARGET_BAR_PX = 15
    HOVER_DELAY_MS = 1000

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
        self._load_seq = 0
        self._loading = False
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
        self._draw_timer = None
        self._pending_view = None
        self._pan_throttle_ms = 33

        self.analyzer = MetricAnalyzer(self.db_path) if self.db_path else None
        
        self._hover_timer = None
        self._hover_tooltip = None
        self._hover_record_id = None
        self._mouse_on_axes = False

        self.fig = Figure(dpi=100)
        self.fig.patch.set_facecolor(COL_BG_DARK)
        self.ax = self.fig.add_subplot(111)
        self.canvas = _FrozenCanvas(self.fig, master=self)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(background=COL_BG_WIDGET)
        self.widget.pack(side="top", fill="x")
        self.fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.18)
        self._style()

        self.widget.bind("<Escape>", lambda e: self._hide_tooltip())

        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("axes_enter_event", self._on_axes_enter)
        self.canvas.mpl_connect("axes_leave_event", self._on_axes_leave)

    def set_frozen(self, frozen):
        self.canvas.set_frozen(frozen)

    @property
    def athlete(self):
        return self._athlete

    @athlete.setter
    def athlete(self, aid):
        self._athlete = aid
        self._start = self._end = None
        self._current_tf = None
        self._hide_tooltip()
        self._reload()

    def set_range(self, start, end):
        self._start, self._end = start, end
        self.view = None
        self._current_tf = None
        self._hide_tooltip()
        self._reload()

    def set_size(self, w, h):
        self.widget.configure(width=w, height=h)

    def set_forced_tf(self, tf):
        self._forced_tf = tf

    def redraw(self):
        self._draw()

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
        self._values = []
        if not self._athlete:
            return
        session = get_session(self.db_path)
        try:
            q = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == self._athlete
            ).order_by(ECGRecord.recorded_at)
            
            if self._start:
                q = q.filter(ECGRecord.recorded_at >= self._start.isoformat() + " 00:00:00")
            if self._end:
                q = q.filter(ECGRecord.recorded_at < self._end.isoformat() + " 23:59:59")
                
            for rec in q.all():
                v = self.spec.value(rec)
                if v is not None:
                    dt = datetime.datetime.fromisoformat(rec.recorded_at)
                    self._values.append((self._ord(dt), v, rec.recorded_at))
        finally:
            session.close()

        if self._start is None and self._values:
            self._start = datetime.date.fromordinal(int(min(d for d, _, _ in self._values)))
            self._end = datetime.date.fromordinal(int(max(d for d, _, _ in self._values)))

    def _start_background_load(self):
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
                pass

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _fetch_values(self, athlete):
        if not athlete:
            return []
        session = get_session(self.db_path)
        try:
            q = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == athlete
            ).order_by(ECGRecord.recorded_at)
            
            if self._start:
                q = q.filter(ECGRecord.recorded_at >= self._start.isoformat() + " 00:00:00")
            if self._end:
                q = q.filter(ECGRecord.recorded_at < self._end.isoformat() + " 23:59:59")
            
            out = []
            for rec in q.all():
                v = self.spec.value(rec)
                if v is not None:
                    dt = datetime.datetime.fromisoformat(rec.recorded_at)
                    out.append((self._ord(dt), v, rec.recorded_at))
            return out
        finally:
            session.close()

    def _apply_background_load(self, seq, athlete, values):
        if seq != self._load_seq or athlete != self._athlete:
            return
        
        self._values = values
        if self._start is None and self._values:
            self._start = datetime.date.fromordinal(int(min(d for d, _, _ in self._values)))
            self._end = datetime.date.fromordinal(int(max(d for d, _, _ in self._values)))
            
        self._loading = False
        self._draw()

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

    def _on_scroll(self, event):
        self._hide_tooltip()  # <-- ДОБАВЛЕНО: скрываем тултип при начале зума
        
        if event.xdata is None or self._start is None:
            return
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        factor = 0.85 if event.button == "up" else 1.18
        width_px = max(100, self.ax.get_window_extent().width)
        min_span = 1.0
        new_span = min(365000, max(min_span, (hi - lo) * factor))
        ratio = (event.xdata - lo) / max(1e-9, hi - lo)
        new_lo = event.xdata - ratio * new_span
        new_hi = new_lo + new_span
        self._commit_view(new_lo, new_hi)

    def _on_press(self, event):
        self._hide_tooltip()
        
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
        if self._pan is not None and event.button == 1:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
                self._single_timer = None
            
            self._hide_tooltip()
                
            x0, lo0, hi0 = self._pan
            width_px = self.ax.get_window_extent().width
            if width_px <= 1:
                return
                
            span = hi0 - lo0
            shift = (x0 - event.x) * span / width_px
            
            new_lo = lo0 + shift
            new_hi = new_lo + span
            self._pending_view = (new_lo, new_hi)

            if self._draw_timer is not None:
                self.after_cancel(self._draw_timer)
            
            self._draw_timer = self.after(16, self._apply_pending_view)
            return
        
        if self._mouse_on_axes and event.xdata is not None:
            self._check_hover(event.xdata)
        else:
            self._hide_tooltip()

    def _apply_pending_view(self):
        self._draw_timer = None
        if self._pending_view is not None:
            lo, hi = self._pending_view
            self._pending_view = None
            self._commit_view(lo, hi)        

    def _on_release(self, event):
        if self._draw_timer is not None:
            self.after_cancel(self._draw_timer)
            self._apply_pending_view()
        self._pan = None

    def center_on_week(self, week_start_date):
        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        span = hi - lo
        center = self._ord(week_start_date + datetime.timedelta(days=3))
        self._commit_view(center - span / 2, center + span / 2)

    def _on_axes_enter(self, event):
        self._mouse_on_axes = True

    def _on_axes_leave(self, event):
        self._mouse_on_axes = False
        self._hide_tooltip()

    def _check_hover(self, xdata):
        record = self._find_closest_record(xdata)
        if record is None:
            self._hide_tooltip()
            return
        
        ordinal, value, recorded_at = record
        if self._hover_record_id == recorded_at:
            return
        
        self._hide_tooltip()
        self._hover_record_id = recorded_at
        self._hover_timer = self.after(self.HOVER_DELAY_MS, lambda: self._show_tooltip(recorded_at))

    def _show_tooltip(self, recorded_at):
        self._hover_timer = None
        if self._hover_record_id != recorded_at:
            return
        if not self.analyzer or not self._athlete:
            return
        
        analysis = self.analyzer.analyze_by_date(self._athlete, recorded_at)
        if not analysis:
            return
        
        self._hover_tooltip = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.configure(bg="#2d2d2d", borderwidth=1, relief="solid")
        tw.attributes('-topmost', True)
        
        text = (f"📅 {analysis.recorded_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"{'─' * 40}\n"
                f"{analysis.tp_color} TP: {analysis.tp:.0f} мс² — {analysis.tp_status}\n"
                f"{analysis.stress_color} Стресс: {analysis.stress_si:.0f} у.е. — {analysis.stress_status}\n"
                f"{'─' * 40}\n"
                f"💡 {analysis.recommendation}")
        
        label = tk.Label(
            tw, text=text, justify="left", bg="#2d2d2d", fg="#ffffff",
            font=("Segoe UI", 9), padx=12, pady=10, anchor="w"
        )
        label.pack()
        
        x = self.winfo_pointerx() + 15
        y = self.winfo_pointery() + 15
        
        tw.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        tw_w = tw.winfo_width()
        tw_h = tw.winfo_height()
        
        if x + tw_w > screen_w:
            x = self.winfo_pointerx() - tw_w - 15
        if y + tw_h > screen_h:
            y = self.winfo_pointery() - tw_h - 15
        
        tw.wm_geometry(f"+{x}+{y}")

    def _hide_tooltip(self):
        if self._hover_timer is not None:
            self.after_cancel(self._hover_timer)
            self._hover_timer = None
        
        if self._hover_tooltip is not None:
            try:
                if self._hover_tooltip.winfo_exists():
                    self._hover_tooltip.destroy()
            except Exception:
                pass
            self._hover_tooltip = None
        
        self._hover_record_id = None

    def _find_closest_record(self, xdata):
        if not self._values:
            return None
        
        idx = bisect.bisect_left(self._values, (xdata,))
        candidates = []
        if idx > 0:
            candidates.append(self._values[idx - 1])
        if idx < len(self._values):
            candidates.append(self._values[idx])
        
        if not candidates:
            return None
        
        closest = min(candidates, key=lambda item: abs(item[0] - xdata))
        if abs(closest[0] - xdata) > 0.5:
            return None
        return closest

    def _style(self):
        self.ax.set_facecolor(COL_BG_DARK)
        self.ax.tick_params(colors=COL_TEXT_LIGHT, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(COL_SPINE)
        self.ax.set_autoscale_on(False)

    def _draw(self):
        self._hide_tooltip()  # <-- ДОБАВЛЕНО: гарантированно скрываем тултип при любой перерисовке
        
        ax = self.ax
        ax.clear()
        self._style()

        if not self._values or not self._start:
            ax.set_title(f"{self.spec.name}: нет данных", color=COL_TEXT_DIM, fontsize=9)
            self.canvas.draw_idle()
            return

        v = self._view_ordinals()
        if v is None:
            return
        lo, hi = v
        vspan = max(1, hi - lo)
        width_px = max(100, self.ax.get_window_extent().width)
        
        config = get_chart_config(vspan)
        
        if config.is_proportional:
            bar_size = calc_proportional_bar_size(vspan, width_px, self.TARGET_BAR_PX)
            bw = bar_size * 0.95
            def key(x): return int(x / bar_size) * bar_size
            self._shade_years(ax, lo, hi, pick_year_step(vspan))
            self._set_year_ticks(ax, lo, hi)
            tf_label = f"{bar_size / 365:.1f}г" if bar_size >= 365 else f"{bar_size:.0f}д"
        else:
            tf = config.bar_tf
            self._current_tf = tf
            bw = tf.bar_size * 0.95
            def key(x): return tf.bin_key(x)
            self._shade_tf(ax, lo, hi, config.zebra_tf)
            self._set_x_ticks_small(ax, lo, hi, vspan, config)
            tf_label = tf.label

        start_idx = bisect.bisect_left(self._values, (lo, -float('inf'), ""))
        end_idx = bisect.bisect_right(self._values, (hi, float('inf'), "zzz"))
        view_values = self._values[start_idx:end_idx]

        agg = {}
        for x, vv, _ in view_values:
            agg.setdefault(key(x), []).append(vv)
        
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs] if xs else []

        if xs and ys:
            c = self.spec.color
            colors = [c(vv) for vv in ys] if callable(c) else (c or COL_TP_YEAR)
            ax.bar(xs, ys, width=bw, color=colors, align="edge", zorder=2, rasterized=True)

        ax.set_xlim(lo, hi)
        if ys:
            ax.set_ylim(0, (max(ys) or 1) * 1.1)
        else:
            ax.set_ylim(0, 1)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)

        d0 = datetime.date.fromordinal(max(1, int(lo)))
        d1 = datetime.date.fromordinal(max(1, int(hi)))
        range_str = f"{d0:%d.%m.%y}–{d1:%d.%m.%y}"
        ax.set_title(f"{self.spec.name} | {tf_label} ({range_str})", color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    def _set_x_ticks_small(self, ax, lo, hi, vspan, config):
        """
        УНИВЕРСАЛЬНАЯ отрисовка. Работает исключительно на основе параметров из ChartConfig.
        """
        ticks, names = [], []
        raw_ticks = []

        # 1. Определяем шаг и тип данных на основе конфига
        if config.tick_step_hours > 0:
            step = datetime.timedelta(hours=config.tick_step_hours)
            current = datetime.datetime.fromordinal(max(1, int(lo))).replace(hour=0, minute=0, second=0)
            is_datetime = True
        else:
            step = datetime.timedelta(days=max(1, config.tick_step_days))
            start_date = datetime.date.fromordinal(max(1, int(lo)))
            
            # Сдвигаем к ближайшему понедельнику, который >= начала диапазона
            if step.days >= 7:
                days_since_monday = start_date.weekday()  # 0=пн, 1=вт, ..., 6=вс
                if days_since_monday == 0:
                    current = start_date
                else:
                    current = start_date + datetime.timedelta(days=(7 - days_since_monday))
            else:
                current = start_date
                
            is_datetime = False

        # 2. Генерируем все возможные точки (тики по понедельникам)
        while True:
            tick_val = self._ord(current)
                
            if tick_val > hi + 0.5:
                break
                
            raw_ticks.append((tick_val, current))
            
            if not is_datetime and current > datetime.date.fromordinal(max(1, int(hi))):
                break
                
            current += step

        # 3. 🔧 ДОБАВЛЯЕМ 1-Е ЧИСЛО КАЖДОГО МЕСЯЦА (если show_month_label=True)
        if getattr(config, 'show_month_label', False) and not is_datetime:
            d_start = datetime.date.fromordinal(max(1, int(lo)))
            d_end = datetime.date.fromordinal(max(1, int(hi)))
            
            # Находим первое 1-е число в диапазоне
            first_first = d_start.replace(day=1)
            if first_first < d_start:
                if first_first.month == 12:
                    first_first = first_first.replace(year=first_first.year + 1, month=1)
                else:
                    first_first = first_first.replace(month=first_first.month + 1)
            
            # Добавляем все 1-е числа месяца
            current_first = first_first
            while current_first <= d_end:
                tick_val = current_first.toordinal()
                # Добавляем только если еще нет такого тика
                if not any(abs(tv - tick_val) < 0.1 for tv, _ in raw_ticks):
                    raw_ticks.append((tick_val, current_first))
                
                # Переходим к следующему месяцу
                if current_first.month == 12:
                    current_first = current_first.replace(year=current_first.year + 1, month=1)
                else:
                    current_first = current_first.replace(month=current_first.month + 1)

        # 4. Сортируем все тики по дате
        raw_ticks.sort(key=lambda x: x[0])

        # 5. Фильтруем только те точки, которые попадают в видимый диапазон
        valid_ticks = [(tv, dt) for tv, dt in raw_ticks if lo - 0.1 <= tv <= hi + 0.1]

        # 6. Форматируем
        for i, (tick_val, dt_obj) in enumerate(valid_ticks):
            ticks.append(tick_val)

            is_first = (i == 0)
            is_last = (i == len(valid_ticks) - 1)
            is_edge = is_first or is_last

            # Выбираем формат по приоритету
            if is_edge and config.force_edge_format and config.tick_edge_format:
                fmt = config.tick_edge_format
            elif config.tick_inner_format:
                fmt = config.tick_inner_format
            else:
                fmt = config.tick_format

            # === 🔧 УПРОЩЕННАЯ ЛОГИКА ФОРМАТИРОВАНИЯ ===
            if fmt == "weekday":
                if getattr(config, 'weekday_date_on_monday', False) and dt_obj.weekday() == 0:
                    names.append(dt_obj.strftime("%d"))
                else:
                    names.append(WEEKDAYS_RU[dt_obj.weekday()])
                    
            elif fmt == "month_short":
                d = dt_obj.date() if isinstance(dt_obj, datetime.datetime) else dt_obj
                if d.day == 1:
                    names.append(MONTHS_RU[d.month - 1])
                    
            else:
                # Показываем месяц 1-го числа (любой день недели)
                if getattr(config, 'show_month_label', False) and dt_obj.day == 1:
                    names.append(MONTHS_RU[dt_obj.month - 1])
                else:
                    # Все остальные случаи — показываем число
                    names.append(dt_obj.strftime(fmt))

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
        if sib is TimeFrame.HOUR1:
            return d + datetime.timedelta(hours=1)
        if sib is TimeFrame.HOUR3:
            return d + datetime.timedelta(hours=3)
        if sib is TimeFrame.DAY:
            return d + datetime.timedelta(days=1)
        if sib is TimeFrame.WEEK:
            return d + datetime.timedelta(days=7)
        return d + datetime.timedelta(days=1)

    def _shade_tf(self, ax, lo, hi, sib):
        step = sib.bar_size
        if step <= 0:
            return
        start_x = sib.bin_key(lo) - step
        x = start_x
        while x <= hi:
            x0, x1 = x, x + step
            if x1 > lo and x0 < hi:
                if int(round(x0 / step)) % 2:
                    ax.axvspan(max(x0, lo), min(x1, hi), color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
                if lo < x0 < hi:
                    ax.axvline(x0, color=COL_TEXT_DIM, linewidth=0.6, alpha=0.35, zorder=0)
            x = x1

    def _shade_years(self, ax, lo, hi, n):
        start_year = max(1, datetime.date.fromordinal(int(lo)).year)
        y = (start_year // n) * n - n
        while y <= 9999:
            x0 = datetime.date(max(1, y), 1, 1).toordinal()
            if x0 > hi:
                break
            x1 = datetime.date(min(9999, y + n), 1, 1).toordinal()
            if x1 > lo and x0 < hi:
                if (y // n) % 2:
                    ax.axvspan(max(x0, lo), min(x1, hi), color=COL_TEXT_LIGHT, alpha=0.06, zorder=0)
                if lo < x0 < hi:
                    ax.axvline(x0, color=COL_TEXT_DIM, linewidth=0.6, alpha=0.35, zorder=0)
            y += n

    @staticmethod
    def _tick_label(sib, d, vspan):
        if sib is TimeFrame.HOUR1:
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