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

        # ✅ Получаем ссылку на корневое окно для прослушивания событий
        self.root = heatmap.winfo_toplevel()
        
        # ✅ Подписываемся на сигнал об изменении данных в БД
        self.root.bind("<<ECGDataChanged>>", self._on_ecg_data_changed)

        # --- Существующие привязки ---
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

    # ================= НОВЫЙ ОБРАБОТЧИК =================

    def _on_ecg_data_changed(self, event=None):
        """
        Реагирует на сигнал <<ECGDataChanged>>.
        Вызывается при удалении/добавлении записей ЭКГ.
        """

        # 1. Обновляем Heatmap (год и неделю)
        # В heatmap.py уже есть метод refresh(), который вызывает _load_data() у карт
        if hasattr(self.heatmap, 'refresh'):
            self.heatmap.refresh()
            
        # 2. Обновляем Графики (Charts)
        # В charts.py уже есть метод refresh(), который вызывает _reload() у каждого графика
        if hasattr(self.charts, 'refresh'):
            self.charts.refresh()
            
        # 3. Сбрасываем сохраненный диапазон зума, чтобы избежать конфликтов 
        # между старым кэшем и новыми данными при следующем взаимодействии
        self._saved_range = None 
       

    # ================= СУЩЕСТВУЮЩИЕ ОБРАБОТЧИКИ =================

    def _on_range_changed(self, lo, hi):
        self._saved_range = (lo, hi)

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
        """ПКМ: показать весь период данных, курсор на последнюю запись."""
        self._saved_range = None
        
        # 0. Гарантируем, что heatmap тоже сбросил свои внутренние кэши до начала работы
        if hasattr(self.heatmap, 'refresh'):
            self.heatmap.refresh()
        
        # 1. ПРИНУДИТЕЛЬНО обнуляем кэш дат. 
        # БЕЗ этого шага _load_sync пропустит пересчет и оставит старый год (2024).
        for p in self.charts._plots:
            p._start = None
            p._end = None
            p.view = None
            
        # 2. Синхронно перезагружаем данные из БД. 
        # Мы ждем завершения (async_load=False), чтобы гарантированно получить 
        # новые _start и _end перед тем, как искать last_date.
        # (SQLite отрабатывает за доли миллисекунды, GUI не "подвиснет")
        for p in self.charts._plots:
            p._reload(async_load=False)
            
        # 3. Ищем актуальную последнюю дату ПОСЛЕ того, как кэш гарантированно обновился
        last_date = None
        for p in self.charts._plots:
            if p._end is not None:
                if last_date is None or p._end > last_date:
                    last_date = p._end
        
        # 4. Обновляем интерфейс только если данные действительно есть (защита от краша)
        if last_date is not None:
            self.heatmap.set_cursor_by_date(last_date)
            self.heatmap.year = last_date.year
            
        # 5. Принудительно перерисовываем графики с новыми границами (view=None)
        self.charts.redraw()
        
        # 6. Финальная синхронизация heatmap
        self.heatmap.reset_to_data_last()

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

    # ================= ПУБЛИЧНЫЕ МЕТОДЫ =================

    def sync_athlete(self, aid):
        """Смена атлета с сохранением текущего масштаба (или сбросом в полный диапазон)."""
        saved = self._saved_range
        self.heatmap.athlete = aid
        self.charts.athlete = aid
        
        if saved is not None:
            self.charts.zoom = saved
        else:
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