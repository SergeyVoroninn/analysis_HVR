"""
app_constants.py — централизованные строковые константы, расширения и сентинелы приложения.
"""

# --- Файлы и расширения ---
ECG_FILE_EXTENSION = ".teamloggerh10"
CONFIG_YAML_PATH = "config.yaml"
ECG_PROFILES_YAML_PATH = "ecg_profiles.yaml"
APP_SETTINGS_FILENAME = "app_settings.json"
SPLASH_LOGO_FILENAME = "logo21.png"     # Логотип заставки

# --- Биометрические сентинелы (замена магического 9999) ---
BIOMETRIC_ERROR_DISTANCE = 9999.0

# --- UI и взаимодействие ---
DOUBLE_CLICK_THRESHOLD_SEC = 0.45
HOVER_TOLERANCE_ORDINAL = 0.5
MAX_ZOOM_ORDINALS = 365000
ECGLIST_DEFAULT_LIMIT = 100
MAX_YEAR = 9999                # Верхняя граница года (datetime.date)

# --- Задержки одиночного клика (мс, до срабатывания действия) ---
SINGLE_CLICK_DELAY_METRICPLOT_MS = 500
SINGLE_CLICK_DELAY_YEARMAP_MS = 300
SINGLE_CLICK_DELAY_WEEKMAP_MS = 350
SINGLE_CLICK_DELAY_ATLETS_MS = 350

# --- Отрисовка графиков ---
PAN_REDRAW_MS = 16          # Интервал отложенной перерисовки при панорамировании (~60 fps)
ZOOM_IN_FACTOR = 0.85       # Коэффициент зума при прокрутке вверх
ZOOM_OUT_FACTOR = 1.18      # Коэффициент зума при прокрутке вниз
MIN_ZOOM_SPAN_DAYS = 1.0    # Минимальный span графика (дни)
DOUBLE_CLICK_PX_TOLERANCE = 6  # Пиксельный допуск для двойного клика
MID_WEEK_OFFSET_DAYS = 3    # Смещение к середине недели (среда)

# --- Тайминги приложения ---
STATUS_TIMEOUT_MS = 8000    # Автоочистка статус-бара (мс)
WHEEL_LOCK_SEC = 0.2        # Дребезг колеса мыши (сек)
IMPORT_PROGRESS_STEP = 10   # Шаг обновления прогресса импорта
WEEK_ZOOM_HALF_RANGE_DAYS = 15  # Полуширина зума на неделю (дни)
DEFAULT_WEEK = 26           # Неделя по умолчанию при переключении года

# --- Пороги бизнес-логики (Импорт и Сортировка) ---
IMPORT_RELATIVE_PROB_THRESHOLD = 0.15
IMPORT_UNKNOWN_PROB_THRESHOLD = 0.15
SORT_LARGE_GROUP_THRESHOLD = 50
SORT_STRICT_THRESHOLD = 0.12

# --- Целевые метрики качества ЭКГ (по умолчанию, для скриптов генерации/калибровки) ---
DEFAULT_QUALITY_TARGETS = {
    'min_snr': 15.0,
    'max_artifact_pct': 2.0,
    'max_baseline_drift': 50.0,
}

# --- Параметры калибровки (скрипты calibrate_ecg / fit_profile_from_real) ---
R_PEAK_AMPLITUDE_THRESHOLD = 500    # Минимальная амплитуда R-пика в остаточном сигнале

# --- Жестко заданные пары родственников (для PoC и тестов) ---
# В продакшене это должно храниться в БД, но для скриптов выносим сюда
HARDCODED_RELATIVE_PAIRS = [("filipp", "trofim")]

# --- Параметры PID-прогнозирования (подводка к соревнованиям) ---
PID_HISTORY_DAYS = 14.0          # Глубина анализа истории (дней)
PID_FORECAST_DAYS = 1           # На сколько дней вперед прогнозируем
PID_MIN_POINTS = 3              # Минимум точек для расчета (иначе шум)

# Коэффициенты регулятора (сумма ~1.0 для стабильности)
PID_DEFAULT_KP = 0.30           # Вес текущего импульса (последнее изменение)
PID_DEFAULT_KI = 0.50           # Вес накопленного тренда (среднее за период)
PID_DEFAULT_KD = 0.40           # Вес ускорения/торможения (изменение изменения)

# Физиологические ограничения прогноза
PID_TP_MAX = 20000.0            # Максимальный разумный TP (мс²)
PID_TP_MIN = 100.0              # Минимальный разумный TP
PID_STRESS_MAX = 200.0          # Максимальный индекс стресса
PID_STRESS_MIN = 0.0