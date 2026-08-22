"""
orchestrator.py — централизованный менеджер состояния приложения.
"""
import datetime


class AppOrchestrator:
    def __init__(self, heatmap, charts, settings):
        self.heatmap = heatmap
        self.charts = charts
        self.settings = settings
        self._saved_range = None  # (lo, hi) в ординалах

        self.heatmap.on_week_pick = self._handle_week_pick
        self.heatmap.on_week_dbl_pick = self._handle_week_dbl_pick
        self.heatmap.on_month_zoom = self._handle_month_zoom
        self.heatmap.on_year_zoom = self._handle_year_zoom
        self.heatmap.on_year_change = self._handle_year_change
        
        self.charts.set_year_pick_callback(self._handle_chart_year_pick)
        self.charts.set_reset_callback(self._handle_chart_reset)
        self.charts.set_single_click_callback(self._handle_chart_single_click)
        self.charts.on_range_changed = self._on_range_changed

        self.heatmap.on_weekmap_day_dbl = self._handle_weekmap_day_dbl
        self.heatmap.on_weekmap_week_rmb = self._handle_weekmap_week_rmb

    def _on_range_changed(self, lo, hi):
        self._saved_range = (lo, hi)

    # ================= Обработчики событий =================

    def _handle_week_pick(self, w, d):
        self.heatmap.week_map.week_start = d
        self.charts.center_on_week(d)

    def _handle_week_dbl_pick(self, w, monday):
        mid_week = monday + datetime.timedelta(days=3)
        start = mid_week - datetime.timedelta(days=15)
        end = mid_week + datetime.timedelta(days=15)
        lo = start.toordinal()
        hi = end.toordinal() + 1
        self.charts.zoom = (lo, hi)

    def _handle_month_zoom(self, start_date, end_date):
        lo = start_date.toordinal()
        hi = end_date.toordinal() + 1
        self.charts.zoom = (lo, hi)

    def _handle_year_zoom(self, start_date, end_date):
        lo = start_date.toordinal()
        hi = end_date.toordinal() + 1
        self.charts.zoom = (lo, hi)

    def _handle_year_change(self, delta):
        self.heatmap.year += delta

    def _handle_chart_year_pick(self, year):
        self.heatmap.year = year

    def _handle_chart_reset(self):
        self._saved_range = None
        for p in self.charts._plots:
            p._start = p._end = None
            p.view = None
            p._reload()
        self.heatmap.reset_to_data_center()

    def _handle_chart_single_click(self, d):
        self.heatmap.set_cursor_by_date(d)

    def _handle_weekmap_day_dbl(self, day_start, day_end):
        lo = day_start.toordinal()
        hi = lo + 1.0
        self.charts.zoom = (lo, hi)

    def _handle_weekmap_week_rmb(self, week_start, week_end):
        lo = week_start.toordinal()
        hi = week_end.toordinal()
        self.charts.zoom = (lo, hi)
        mid_week = (week_start - self.heatmap.year_map._year_start).days // 7
        self.heatmap.week = mid_week

    # ================= Публичные методы =================

    def sync_athlete(self, aid):
        """Смена атлета с сохранением текущего масштаба (или сбросом в полный диапазон)."""
        saved = self._saved_range
        self.heatmap.athlete = aid
        self.charts.athlete = aid
        
        if saved is not None:
            # Если был установлен конкретный зум (колесо, двойной клик), применяем его
            self.charts.zoom = saved
        else:
            # Если был сделан ПКМ (сброс), явно указываем графикам показать полный диапазон нового атлета
            for p in self.charts._plots:
                p.view = None
                
        self.charts.redraw()

    def restore_state(self, saved_athlete_id, saved_year, saved_week, saved_zoom):
        if saved_zoom and len(saved_zoom) == 2 and saved_zoom[0] and saved_zoom[1]:
            self._saved_range = tuple(saved_zoom)
            self.charts.zoom = self._saved_range
        self.heatmap.set_selection(year=saved_year, week=saved_week)

    def save_state(self, current_athlete_id):
        self.settings.set("athlete_id", current_athlete_id)
        self.settings.set("year", self.heatmap.year)
        self.settings.set("week", self.heatmap.week)
        p0 = self.charts._plots[0]
        v = p0._view_ordinals()
        self.settings.set("zoom", list(v) if v else None)
        self.settings.save()