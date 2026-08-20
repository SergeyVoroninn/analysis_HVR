"""
metricplot.py — отрисовка одного графика параметра ЭКГ (ВСР).

Режимы масштаба:
  span <= 365 дней — календарные бары: 3часа / день / неделя
                     (зум внутрь ограничен таймфреймом 3часа);
  span >  365 дней — пропорциональная цена бара ~TARGET_BAR_PX px,
                     зебра и подписи — годы.

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
from timeframe import TimeFrame


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

    MIN_BAR_PX = 6          # уже — шаг на более крупный таймфрейм
    MAX_BAR_PX = 40         # шире — шаг на более мелкий (если он помещается)
    MIN_TF = TimeFrame.HOUR3    # мельче 3 часов не зумируем
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
        self._single_timer = None
        self._click_t = 0.0
        self._click_x = 0.0
        self._click_y = 0.0
        self._current_tf = None
        
        # Callbacks
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

    def redraw(self):
        self._draw()

    # ---------------- данные ----------------
    def _reload(self):
        self._values = []
        if not self._athlete:
            self._draw()
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
        # ИСПРАВЛЕНО: безопасная обработка None для сброса масштаба
        if lo is None or hi is None:
            self.view = None
        else:
            self.view = (float(lo), float(hi))
        
        # ИСПРАВЛЕНО: всегда уведомляем панель, если она есть
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
        # стоп зума внутрь: бар 3часа ровно MAX_BAR_PX
        min_span = width_px * self.MIN_TF.bar_size() / self.MAX_BAR_PX
        new_span = min(365000, max(min_span, (hi - lo) * factor))
        ratio = (event.xdata - lo) / max(1e-9, hi - lo)
        new_lo = event.xdata - ratio * new_span
        new_hi = new_lo + new_span
        self._commit_view(new_lo, new_hi)

    def _on_press(self, event):
        if event.button == 3:
            # ИСПРАВЛЕНО: сброс масштаба теперь проходит через _commit_view(None, None),
            # что гарантирует вызов on_view_changed и обновление ВСЕХ графиков в панели.
            self._current_tf = None
            if self.on_reset:
                self.on_reset()
            self._commit_view(None, None)
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
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
                self._single_timer = None
            d = datetime.date.fromordinal(int(event.xdata))
            self._commit_view(self._ord(datetime.date(d.year, 1, 1)),
                              self._ord(datetime.date(d.year, 12, 31)) + 1)
            if self.on_year_pick:
                self.on_year_pick(d.year)
            return

        if self.on_single_click:
            if self._single_timer is not None:
                self.after_cancel(self._single_timer)
            d = datetime.date.fromordinal(int(event.xdata))
            self._single_timer = self.after(
                300, lambda dd=d: self._fire_single(dd))

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

    # ---------------- выбор таймфрейма (малый диапазон) ----------------
    def _pick_small_tf(self, span, width_px):
        """Календарный tf в зоне [3часа .. неделя]: шаг только на соседний.
        Шаг мельче — только если более мелкий бар реально помещается (>= MIN)."""
        order = list(TimeFrame)
        lo_i = order.index(self.MIN_TF)
        hi_i = order.index(TimeFrame.WEEK)

        cur = self._current_tf
        if cur is None or not (lo_i <= order.index(cur) <= hi_i):
            tf = order[lo_i]
            for t in order[lo_i:hi_i + 1]:
                if (t.bar_size() / span) * width_px <= self.MAX_BAR_PX:
                    tf = t
            return tf

        i = order.index(cur)
        actual = (cur.bar_size() / span) * width_px
        if actual < self.MIN_BAR_PX and i < hi_i:
            return order[i + 1]                       # крупнее
        if actual > self.MAX_BAR_PX and i > lo_i:
            prv = order[i - 1]
            if (prv.bar_size() / span) * width_px >= self.MIN_BAR_PX:
                return prv                            # мельче
        return cur

    @staticmethod
    def _year_step(vspan):
        for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if vspan / (365 * n) <= 12:
                return n
        return 1000

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

        # Проверяем, есть ли вообще данные у атлета (независимо от текущего view)
        has_any_data = bool(self._values)
        
        # Получаем текущий view
        v = self._view_ordinals()
        if v is None:
            # Если view не задан и нет данных вообще
            if not has_any_data or not self._start:
                ax.set_title(f"{self.spec.name}: нет данных",
                             color=COL_TEXT_DIM, fontsize=9)
                self.canvas.draw_idle()
                return
            # Если view не задан, но данные есть — используем полный диапазон
            lo = float(self._ord(self._start))
            hi = float(self._ord(self._end)) + 1
        else:
            lo, hi = v

        vspan = max(1, hi - lo)
        width_px = max(100, self.ax.get_window_extent().width)

        # Фильтруем данные для текущего view
        view_values = [(dt, vv) for dt, vv in self._values 
                       if lo <= self._ord(dt) < hi]

        if vspan <= self.SMALL_SPAN:
            # ---- календарные бары: 3часа / день / неделя ----
            tf = self._pick_small_tf(vspan, width_px)
            self._current_tf = tf
            bw = tf.bar_size() * 0.95
            def key(x): return tf.bin_key(x)
            self._shade_tf(ax, lo, hi, tf.zebra[1])
            self._set_x_ticks_small(ax, lo, hi, vspan, tf)
            tf_label = tf.label
        else:
            # ---- большой диапазон: пропорциональная цена бара ----
            self._current_tf = None
            bars = max(10, int(width_px / self.TARGET_BAR_PX))
            bar_size = vspan / bars
            bw = bar_size * 0.95
            def key(x): return int(x / bar_size) * bar_size
            self._shade_years(ax, lo, hi, self._year_step(vspan))
            self._set_year_ticks(ax, lo, hi)
            tf_label = (f"{bar_size / 365:.1f}г" if bar_size >= 365
                        else f"{bar_size:.0f}д")

        # Агрегируем данные только из view_values
        agg = {}
        for dt, vv in view_values:
            x = self._ord(dt)
            agg.setdefault(key(x), []).append(vv)
        
        xs = sorted(agg)
        ys = [sum(agg[x]) / len(agg[x]) for x in xs] if xs else []

        # Рисуем бары только если есть данные в текущем view
        if xs and ys:
            c = self.spec.color
            colors = [c(vv) for vv in ys] if callable(c) else (c or COL_TP_YEAR)
            ax.bar(xs, ys, width=bw, color=colors, align="edge", zorder=2)

        ax.set_xlim(lo, hi)
        if ys:
            ax.set_ylim(0, (max(ys) or 1) * 1.1)
        else:
            # Если нет данных в view, устанавливаем разумный ylim
            ax.set_ylim(0, 1)
        ax.set_ylabel(self.spec.ylabel, color=COL_TEXT_LIGHT)

        d0 = datetime.date.fromordinal(max(1, int(lo)))
        d1 = datetime.date.fromordinal(max(1, int(hi)))
        range_str = (f"{d0:%d.%m.%y}–{d1:%d.%m.%y}" if vspan > 350
                     else f"{d0:%d.%m}–{d1:%d.%m}")
        ax.set_title(f"{self.spec.name} | {tf_label} ({range_str})",
                     color=COL_TEXT_LIGHT, fontsize=9)
        self.canvas.draw_idle()

    # ---------------- ось X ----------------
    def _set_x_ticks_small(self, ax, lo, hi, vspan, tf):
        bounds = list(self._sibling_bounds(tf.zebra[1], lo, hi))
        mult = 1
        while len(bounds) / mult > 12:
            mult *= 2
        ticks, names = [], []
        for i, d in enumerate(bounds):
            if i % mult:
                continue
            ticks.append(self._ord(d))
            names.append(self._tick_label(tf.zebra[1], d, vspan))
        ax.set_xticks(ticks)
        ax.set_xticklabels(names, fontsize=7)

    def _set_year_ticks(self, ax, lo, hi):
        n = self._year_step(max(1, hi - lo))
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
        if sib is TimeFrame.QUARTER:
            d = datetime.date(d0.year, ((d0.month - 1) // 3) * 3 + 1, 1)
        elif sib is TimeFrame.MONTH:
            d = d0.replace(day=1)
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
        if sib is TimeFrame.QUARTER:
            m = d.month + 3
            return datetime.date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
        if sib is TimeFrame.MONTH:
            return datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        if sib is TimeFrame.WEEK:
            return d + datetime.timedelta(days=7)
        return d + datetime.timedelta(days=1)

    @staticmethod
    def _tick_label(sib, d, vspan):
        if sib is TimeFrame.QUARTER:
            return (str(d.year) if d.month == 1
                    else f"Q{(d.month - 1) // 3 + 1}'{d.year % 100:02d}")
        if sib is TimeFrame.MONTH:
            return str(d.year) if d.month == 1 else d.strftime("%b")
        if sib in (TimeFrame.WEEK, TimeFrame.DAY):
            return d.strftime("%d.%m.%y") if vspan > 350 else d.strftime("%d.%m")
        return d.strftime("%H:%M")

    # ---------------- зебра ----------------
    def _shade_tf(self, ax, lo, hi, sib):
        step = sib.bar_size()
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