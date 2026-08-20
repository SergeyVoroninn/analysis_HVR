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
        self.heatmap.on_month_zoom = self._handle_month_zoom
        self.heatmap.on_year_change = self._handle_year_change
        
        self.charts.set_year_pick_callback(self._handle_chart_year_pick)
        self.charts.set_reset_callback(self._handle_chart_reset)
        self.charts.set_single_click_callback(self._handle_chart_single_click)

    # ================= Обработчики событий =================

    def _handle_week_pick(self, w, d):
        """Одинарный клик по неделе: центрируем графики, обновляем weekmap."""
        self.heatmap.week_map.week_start = d
        self.charts.center_on_week(d)

    def _handle_week_dbl_pick(self, w, d):
        """Двойной клик по неделе: зумим графики на эту неделю."""
        self.heatmap.week_map.week_start = d
        self.charts.zoom_to_week(d)

    def _handle_month_zoom(self, start_date, end_date):
        """ПКМ по месяцу: зумим графики на месяц, ставим курсор на середину месяца."""
        # Устанавливаем диапазон данных
        self.charts.set_range(start_date, end_date)
        
        # Вычисляем ординалы для zoom
        p0 = self.charts._plots[0]
        lo = p0._ord(start_date)
        hi = p0._ord(end_date) + 1
        
        # Устанавливаем zoom на выбранный месяц
        self.charts.zoom = (lo, hi)
        
        # Вычисляем середину месяца
        mid_date = start_date + (end_date - start_date) // 2
        mid_week = (mid_date - self.heatmap.year_map._year_start).days // 7
        self.heatmap.week = mid_week

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