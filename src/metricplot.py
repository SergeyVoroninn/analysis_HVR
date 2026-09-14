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
        self._hover_xdata = None
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

        # Обработка клавиш
        self.widget.bind("<Escape>", lambda e: self._cancel_hover())
        self.widget.bind("<Return>", lambda e: self._open_analysis_dialog())

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
        self._cancel_hover()
        self._reload()

    def set_range(self, start, end):
        self._start, self._end = start, end
        self.view = None
        self._current_tf = None
        self._cancel_hover()
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
        # === КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: если подсказка видна — открываем диалог ===
        if self._hover_tooltip is not None:
            self._open_analysis_dialog()
            return
        # =====================================================================
        
        self._cancel_hover()
        
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
            
            self._cancel_hover()
                
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
        
        # Обработка наведения
        if self._mouse_on_axes and event.xdata is not None:
            self._handle_hover(event.xdata)
        else:
            self._cancel_hover()

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
        self._cancel_hover()

    def _handle_hover(self, xdata):
        # Если окно уже открыто, не прерываем его при микро-движениях
        if self._hover_tooltip is not None:
            return
            
        if self._hover_xdata is not None and abs(self._hover_xdata - xdata) < 0.05:
            return
        
        self._cancel_hover() # Сбрасываем старое при значительном сдвиге
        
        self._hover_xdata = xdata
        self._hover_timer = self.after(self.HOVER_DELAY_MS, lambda: self._show_analysis(xdata))

    def _cancel_hover(self):
        """Полностью сбрасывает состояние наведения."""
        if self._hover_timer is not None:
            self.after_cancel(self._hover_timer)
            self._hover_timer = None
        
        if self._hover_tooltip is not None:
            try:
                self._hover_tooltip.destroy()
            except Exception:
                pass
            self._hover_tooltip = None
        
        self._hover_xdata = None

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

    def _show_analysis(self, xdata):
        """Показывает всплывающую подсказку с анализом."""
        self._hover_timer = None
        
        # ИСПРАВЛЕНИЕ: Не вызываем _cancel_hover(), чтобы не затереть _hover_xdata!
        # Вместо этого просто гарантируем, что старое окно закрыто.
        if self._hover_tooltip is not None:
            try:
                self._hover_tooltip.destroy()
            except Exception:
                pass

        # Сохраняем текущие данные наведения для возможного последующего клика
        self._hover_xdata = xdata
        
        record = self._find_closest_record(xdata)
        if record is None:
            self._cancel_hover()
            return
        
        ordinal, value, recorded_at = record
        
        if not self.analyzer or not self._athlete:
            self._cancel_hover()
            return
        
        analysis = self.analyzer.analyze_by_date(self._athlete, recorded_at)
        if not analysis:
            self._cancel_hover()
            return
        
        # Создаем всплывающее окно
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
        tw.bind("<Motion>", lambda e: self._cancel_hover())

    def _open_analysis_dialog(self):
        """Открывает полноценный диалог анализа для текущей подсказки."""
        if self._hover_xdata is None:
            return
        
        record = self._find_closest_record(self._hover_xdata)
        if record is None:
            return
        
        ordinal, value, recorded_at = record
        
        if not self.analyzer or not self._athlete:
            return
        
        analysis = self.analyzer.analyze_by_date(self._athlete, recorded_at)
        if not analysis:
            return
        
        # Закрываем подсказку перед открытием диалога
        self._cancel_hover()
        
        try:
            from analysis_dialog import AnalysisDialog
            parent_window = self.winfo_toplevel()
            AnalysisDialog(parent_window, analysis, self.db_path)
        except ImportError:
            # Если файла диалога нет, выводим в консоль
            print("\n" + analysis.to_text() + "\n")

    def _style(self):
        self.ax.set_facecolor(COL_BG_DARK)
        self.ax.tick_params(colors=COL_TEXT_LIGHT, labelsize=8)
        for s in self.ax.spines.values():
            s.set_color(COL_SPINE)
        self.ax.set_autoscale_on(False)

    def _draw(self):
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
        ticks, names = [], []
        months_ru = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        weekdays_ru = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
        
        start_ord = max(1, int(lo))
        d0 = datetime.date.fromordinal(start_ord)
        d1 = datetime.date.fromordinal(max(1, int(hi)))
                
        if 1.5 < vspan <= 7:
            current = d0
            while current <= d1:
                ticks.append(current.toordinal())
                if current.weekday() == 0:
                    names.append(current.strftime("%d.%m"))
                else:
                    names.append(weekdays_ru[current.weekday()])
                current += datetime.timedelta(days=1)
        elif vspan <= 1.5:
            current = datetime.datetime(d0.year, d0.month, d0.day, 0, 0, 0)
            while self._ord(current) <= hi + 0.5:
                label = current.strftime("%d.%m") if current.hour == 0 else current.strftime("%H:%M")
                ticks.append(self._ord(current))
                names.append(label)
                current += datetime.timedelta(hours=3)
        elif config.tick_format == "3hour" and config.tick_step_hours > 0:
            current = datetime.datetime(d0.year, d0.month, d0.day, 0, 0, 0)
            step = datetime.timedelta(hours=config.tick_step_hours)
            while self._ord(current) <= hi + 0.5:
                if current.hour == 0:
                    wd = weekdays_ru[current.weekday()]
                    label = f"{wd} {current.strftime('%d.%m')}"
                else:
                    label = current.strftime("%H:%M")
                ticks.append(self._ord(current))
                names.append(label)
                current += step
        elif config.bar_tf is TimeFrame.DAY and vspan > 31:
            current = d0.replace(day=1)
            if current < d0:
                current = current.replace(year=current.year + 1, month=1) if current.month == 12 else current.replace(month=current.month + 1)
            while current <= d1:
                ticks.append(current.toordinal())
                names.append(months_ru[current.month - 1])
                current = current.replace(year=current.year + 1, month=1) if current.month == 12 else current.replace(month=current.month + 1)
        elif config.bar_tf is TimeFrame.HOUR3:
            current = datetime.datetime(d0.year, d0.month, d0.day, 0, 0, 0)
            step = datetime.timedelta(days=1)
            while self._ord(current) <= hi + 0.5:
                if current.hour == 0:
                    weekday_num = current.weekday()
                    if weekday_num == 0:
                        label = current.strftime('%d.%m')
                    else:
                        label = weekdays_ru[weekday_num]
                else:
                    label = current.strftime("%H:%M")
                ticks.append(self._ord(current))
                names.append(label)
                current += step
        else:
            bounds = list(self._sibling_bounds(config.zebra_tf, lo, hi))
            last_tick_ord = -999
            for d in bounds:
                d_ord = self._ord(d)
                if d_ord - last_tick_ord < config.tick_step_days:
                    continue
                ticks.append(d_ord)
                names.append(d.strftime(config.tick_format))
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