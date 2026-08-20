"""
orchestrator.py — централизованный менеджер состояния приложения.
Координирует взаимодействие между виджетами: Heatmap, ChartsPanel, AthletesPanel.
"""
import datetime


class AppOrchestrator:
    """
    Оркестратор приложения. Хранит ссылки на основные виджеты и обрабатывает
    все события пользовательского ввода, синхронизируя состояние между ними.
    """
    
    def __init__(self, heatmap, charts, settings):
        self.heatmap = heatmap
        self.charts = charts
        self.settings = settings

        # Подписываем "сырые" события виджетов на методы оркестратора
        self.heatmap.on_week_pick = self._handle_week_pick
        self.heatmap.on_week_dbl_pick = self._handle_week_dbl_pick
        self.heatmap.on_year_zoom = self._handle_year_zoom
        self.heatmap.on_month_zoom = self._handle_month_zoom
        self.heatmap.on_year_zoom = self._handle_year_zoom
        self.heatmap.on_year_change = self._handle_year_change
        
        self.charts.set_year_pick_callback(self._handle_chart_year_pick)
        self.charts.set_reset_callback(self._handle_chart_reset)
        self.charts.set_single_click_callback(self._handle_chart_single_click)

        self.heatmap.on_weekmap_day_dbl = self._handle_weekmap_day_dbl
        self.heatmap.on_weekmap_week_rmb = self._handle_weekmap_week_rmb

    # ================= Обработчики событий =================

    def _handle_week_pick(self, w, d):
        """Одинарный клик по неделе: центрируем графики, обновляем weekmap."""
        self.heatmap.week_map.week_start = d
        self.charts.center_on_week(d)

    def _handle_week_dbl_pick(self, w, monday):
        """Двойной клик по yearmap: диапазон месяц ±15 дней от курсора."""
        mid_week = monday + datetime.timedelta(days=3)  # четверг — середина недели
        start = mid_week - datetime.timedelta(days=15)
        end = mid_week + datetime.timedelta(days=15)
        self.charts.set_range(start, end)

    def _handle_month_zoom(self, start_date, end_date):
        """ПКМ по месяцу на графиках: зум на месяц."""
        self.charts.set_range(start_date, end_date)

    def _handle_year_zoom(self, start_date, end_date):
        """ПКМ по yearmap: зум на весь год."""
        self.charts.set_range(start_date, end_date)

    def _handle_year_change(self, delta):
        """Смена года колесиком."""
        self.heatmap.year += delta

    def _handle_chart_year_pick(self, year):
        """Клик по году на графике: синхронизируем heatmap."""
        self.heatmap.year = year

    def _handle_chart_reset(self):
        """Сброс зума на графиках: возвращаем heatmap в центр данных."""
        self.heatmap.reset_to_data_center()

    def _handle_chart_single_click(self, d):
        """Клик по бару на графике: перемещаем курсор heatmap на эту дату."""
        self.heatmap.set_cursor_by_date(d)

    # ================= Публичные методы для управления извне =================

    def sync_athlete(self, aid):
        """Централизованная смена атлета с сохранением масштаба."""
        # Сохраняем текущий zoom (диапазон графика)
        saved_zoom = self.charts.zoom
        
        # Меняем атлета (это сбросит данные и перерисует графики)
        self.heatmap.athlete = aid
        self.charts.athlete = aid
        
        # Восстанавливаем zoom, если он был установлен
        if saved_zoom:
            self.charts.zoom = saved_zoom
            self.charts.redraw()

    def restore_state(self, saved_athlete_id, saved_year, saved_week, saved_zoom):
        """Восстановление состояния при старте."""
        if saved_zoom and len(saved_zoom) == 2 and saved_zoom[0] and saved_zoom[1]:
            self.charts.zoom = tuple(saved_zoom)
        
        self.heatmap.set_selection(year=saved_year, week=saved_week)

    def save_state(self, current_athlete_id):
        """Сохранение состояния при закрытии."""
        self.settings.set("athlete_id", current_athlete_id)
        self.settings.set("year", self.heatmap.year)
        self.settings.set("week", self.heatmap.week)
        z = self.charts.zoom
        self.settings.set("zoom", list(z) if z else None)
        self.settings.save()

    def _handle_weekmap_day_dbl(self, day_start, day_end):
        """Двойной клик по дню в weekmap: зумим графики на сутки."""
        # В metricplot _view_ordinals добавляет +1 к _end,
        # поэтому передаём day_start и как начало, и как конец = 1 день
        self.charts.set_range(day_start, day_start)

    def _handle_weekmap_week_rmb(self, week_start, week_end):
        self.charts.set_range(week_start, week_end)
        mid_week = (week_start - self.heatmap.year_map._year_start).days // 7
        self.heatmap.week = mid_week