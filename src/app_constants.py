"""
app_constants.py — централизованные строковые константы, расширения и сентинелы приложения.
"""

# --- Файлы и расширения ---
ECG_FILE_EXTENSION = ".teamloggerh10"
CONFIG_YAML_PATH = "config.yaml"
ECG_PROFILES_YAML_PATH = "ecg_profiles.yaml"

# --- Биометрические сентинелы (замена магического 9999) ---
BIOMETRIC_ERROR_DISTANCE = 9999.0

# --- UI и взаимодействие ---
DOUBLE_CLICK_THRESHOLD_SEC = 0.45
HOVER_TOLERANCE_ORDINAL = 0.5
MAX_ZOOM_ORDINALS = 365000
ECGLIST_DEFAULT_LIMIT = 100

# --- Пороги бизнес-логики (Импорт и Сортировка) ---
IMPORT_RELATIVE_PROB_THRESHOLD = 0.25
IMPORT_UNKNOWN_PROB_THRESHOLD = 0.20
SORT_LARGE_GROUP_THRESHOLD = 50
SORT_STRICT_THRESHOLD = 0.12

# --- Жестко заданные пары родственников (для PoC и тестов) ---
# В продакшене это должно храниться в БД, но для скриптов выносим сюда
HARDCODED_RELATIVE_PAIRS = [("filipp", "trofim")]