"""
app_constants.py — централизованные строковые константы, расширения и сентинелы приложения.
"""

# --- Файлы и расширения ---
ECG_FILE_EXTENSION = ".teamloggerh10"
CONFIG_YAML_PATH = "config.yaml"
ECG_PROFILES_YAML_PATH = "ecg_profiles.yaml"
APP_SETTINGS_FILENAME = "app_settings.json"

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

# --- Пороги бизнес-логики (Импорт и Сортировка) ---
IMPORT_RELATIVE_PROB_THRESHOLD = 0.25
IMPORT_UNKNOWN_PROB_THRESHOLD = 0.20
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