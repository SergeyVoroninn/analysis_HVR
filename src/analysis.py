"""
Анализ ЭКГ: парсинг сырых данных и расчёт метрик HRV.
Используется и при генерации БД, и в приложении.

Зависимости: numpy, scipy
Установка: pip install numpy scipy
"""

import re
import numpy as np
from scipy import signal
from scipy.signal import butter, filtfilt, iirnotch
from scipy.integrate import trapezoid
from scipy.ndimage import median_filter

# ==============================================================================
# КОНФИГУРАЦИЯ (Устранение хардкода и магических чисел)
# ==============================================================================
class AnalysisConfig:
    # --- Границы частоты сердечных сокращений (ЧСС) ---
    HR_CRIT = (35, 200)    # выход за эти границы → красный
    HR_WARN = (45, 180)    # выход за эти границы → жёлтый

    # --- Параметры парсинга ---
    METADATA_LINES_TO_CHECK = 50
    MIN_RR_INTERVALS_HARDWARE = 10
    MIN_ECG_SAMPLES_FOR_FALLBACK = 100
    DEFAULT_FS = 130.0

    # --- Параметры спектрального анализа (PSD) ---
    PSD_RESAMPLE_FS = 4.0           # Частота интерполяции для спектрального анализа
    VLF_BAND = (0.0033, 0.04)       # Very Low Frequency (стандарт Task Force)
    LF_BAND = (0.04, 0.15)          # Low Frequency
    HF_BAND = (0.15, 0.4)           # High Frequency

    # --- Параметры расчета стресса (Баевский) ---
    MIN_RR_FOR_STRESS = 10
    STRESS_THRESHOLDS = {
        "low": 30,
        "moderate": 80,
        "high": 150
    }
    STRESS_PERCENTILES = [99, 1]
    HISTOGRAM_BIN_WIDTH_SEC = 0.02

    # --- Параметры расчета базовых метрик ---
    MIN_RR_FOR_METRICS = 3

    # --- Параметры очистки ЭКГ ---
    MIN_ECG_SAMPLES_TO_CLEAN = 100
    OUTLIER_IQR_MULTIPLIER = 3.0    # Множитель IQR для поиска выбросов
    MEDIAN_FILTER_SIZE = 5          # Размер окна медианного фильтра
    NOTCH_FREQ = 50.0               # Частота сети
    NOTCH_Q = 30.0                  # Добротность режекторного фильтра
    BANDPASS_LOW = 0.5              # Нижняя граница полосового фильтра
    BANDPASS_HIGH = 50.0            # Верхняя граница полосового фильтра
    BUTTERWORTH_ORDER = 4           # Порядок фильтра Баттерворта

    # --- Параметры детекции R-пиков (fallback из ЭКГ) ---
    MIN_PEAKS_FOR_RR = 2
    MIN_RR_MS = 300                 # Минимальный физиологический RR (200 уд/мин)
    MAX_RR_MS = 1500                # Максимальный физиологический RR (40 уд/мин)
    PEAK_PROMINENCE_RATIO = 0.4     # Доля от размаха сигнала для prominence
    DEFAULT_RR_REPLACEMENT_MS = 800.0 # Значение по умолчанию при пропуске пика

    # --- Пороги статуса записи ---
    RMSSD_CRIT_THRESHOLD = 5
    RMSSD_WARN_THRESHOLD = 10

    # --- Параметры фильтрации RR-интервалов ---
    MIN_RR_TO_FILTER = 10
    RR_FILTER_DEVIATION = 0.25      # Максимальное отклонение от скользящей медианы (25%)
    RR_FILTER_WINDOW_SIZE = 9

    # ==============================================================================
    # ✅ ДОБАВЛЕНО: Пороги для analyzer.py (Total Power и Индекс Стресса)
    # ==============================================================================
    TP_THRESHOLDS = {
        "excellent": 8000,
        "good": 5000,
        "moderate": 3000,
        "low": 1500
    }

    SI_THRESHOLDS = {
        "low": 150,
        "moderate": 300,
        "high": 500
    }

# Глобальный экземпляр конфигурации
cfg = AnalysisConfig()


def detect_sampling_rate(raw_data):
    """
    Пытается определить частоту дискретизации из метаданных файла.
    Возвращает fs в Гц или None, если не удалось определить.
    """
    lines = raw_data.split('\n')
    for line in lines[:cfg.METADATA_LINES_TO_CHECK]:
        line_upper = line.strip().upper()
        if 'SAMPLE RATE' in line_upper or 'SAMPLING RATE' in line_upper or 'HZ' in line_upper or 'ГЦ' in line_upper:
            try:
                match = re.search(r'(\d+)', line)
                if match:
                    return float(match.group(1))
            except Exception:
                pass
    return None


def compute_psd(rr, fs=None, nperseg=None):
    """
    Спектральная плотность RR-тахограммы.
    """
    if fs is None:
        fs = cfg.PSD_RESAMPLE_FS
        
    rr_clean = filter_rr(rr)
    rr_arr = np.asarray(rr_clean, dtype=float)
    if len(rr_arr) < 4:
        return None, None, None

    t = np.cumsum(rr_arr) / 1000.0
    t_uniform = np.arange(t[0], t[-1], 1.0 / fs)
    x = np.interp(t_uniform, t, rr_arr)
    x = x - np.mean(x)

    if nperseg is None or nperseg > len(x):
        nperseg = len(x)
        
    freqs, psd = signal.welch(x, fs=fs, nperseg=nperseg, window='hann')

    def band_power(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return float(trapezoid(psd[mask], freqs[mask]))

    # Используем диапазоны из конфига
    bands = {
        "vlf": band_power(*cfg.VLF_BAND),
        "lf":  band_power(*cfg.LF_BAND),
        "hf":  band_power(*cfg.HF_BAND),
    }
    bands["tp"] = bands["vlf"] + bands["lf"] + bands["hf"]
    
    return freqs, psd, bands


def stress_level(si):
    """Текстовый уровень стресса по индексу напряжения (Баевский)."""
    if si is None:
        return None
    th = cfg.STRESS_THRESHOLDS
    if si < th["low"]:      return "низкий"
    if si < th["moderate"]: return "умеренный"
    if si < th["high"]:     return "высокий"
    return "перенапряжение"


def calc_stress(rr):
    rr_clean = filter_rr(rr)
    
    if len(rr_clean) < cfg.MIN_RR_FOR_STRESS:
        return None
    
    vals_sec = np.array(rr_clean) / 1000.0
    
    p99, p1 = np.percentile(vals_sec, cfg.STRESS_PERCENTILES)
    mxdmn = p99 - p1
    if mxdmn <= 0:
        return None

    mn, mx = np.min(vals_sec), np.max(vals_sec)
    bin_w = cfg.HISTOGRAM_BIN_WIDTH_SEC
    
    if mx - mn < bin_w:
        bin_w = mx - mn
        
    counts, bin_edges = np.histogram(vals_sec, bins=np.arange(mn, mx + bin_w, bin_w))
    
    max_count = np.max(counts)
    mode_idx = np.argmax(counts)
    mo = bin_edges[mode_idx] + 0.5 * bin_w
    
    amo = (max_count / len(vals_sec)) * 100.0
    si = amo / (mo * mxdmn)

    return {
        "si": float(si), 
        "amo": float(amo), 
        "mo_ms": float(mo * 1000),
        "mxdmn_ms": float(mxdmn * 1000), 
        "level": stress_level(si)
    }


def parse_rr(raw_data, fs=None):
    """
    Извлекает RR-интервалы (мс) из сырой записи.
    ПРИОРИТЕТ: Сначала читаем готовые аппаратные данные из [RR].
    Только если их нет, пытаемся извлечь из [ECG].
    """
    if fs is None:
        fs = detect_sampling_rate(raw_data)
        if fs is None:
            fs = cfg.DEFAULT_FS
            
    lines = raw_data.split('\n')
    
    in_rr = False
    rr = []
    for line in lines:
        line = line.strip()
        if line == '[RR]':
            in_rr = True
            continue
        if line.startswith('['):
            in_rr = False
            continue
        if in_rr and line:
            try:
                rr.extend(int(v) for v in line.split(',') if v.strip())
            except ValueError:
                pass
    
    if len(rr) > cfg.MIN_RR_INTERVALS_HARDWARE:
        return rr

    if '[ECG]' in raw_data:
        in_ecg = False
        samples = []
        for line in lines:
            line = line.strip()
            if line == '[ECG]':
                in_ecg = True
                continue
            if line.startswith('['):
                in_ecg = False
                continue
            if in_ecg and ':' in line:
                data_part = line.split(':', 1)[1]
                try:
                    samples.extend(int(v) for v in data_part.split(',') if v.strip())
                except ValueError:
                    pass
        
        if len(samples) > cfg.MIN_ECG_SAMPLES_FOR_FALLBACK:
            ecg_clean = clean_ecg(samples, fs=fs)
            rr_from_ecg = extract_rr_from_ecg(ecg_clean, fs=fs)
            if rr_from_ecg and len(rr_from_ecg) > cfg.MIN_RR_INTERVALS_HARDWARE:
                return rr_from_ecg
    
    return rr


def calc_metrics(rr):
    """
    Расчёт метрик HRV с предварительной фильтрацией RR.
    """
    rr_clean = filter_rr(rr)
    
    n = len(rr_clean)
    if n < cfg.MIN_RR_FOR_METRICS:
        return None

    rr_array = np.array(rr_clean, dtype=float)
    mean_rr = np.mean(rr_array)
    sdnn = np.std(rr_array, ddof=1)
    diffs = np.diff(rr_array)
    rmssd = np.sqrt(np.mean(np.square(diffs)))
    mean_hr = 60000.0 / mean_rr
    
    return {
        "mean_hr": float(mean_hr),
        "min_hr": float(60000.0 / np.max(rr_array)),
        "max_hr": float(60000.0 / np.min(rr_array)),
        "mean_rr": float(mean_rr),
        "sdnn": float(sdnn),
        "rmssd": float(rmssd),
        "count": n,
        "status": _status(mean_hr, rmssd),
    }


def parse_ecg(raw_data, clean=False, fs=None):
    """
    Извлекает семплы сигнала ЭКГ из сырой записи.
    """
    if fs is None:
        fs = detect_sampling_rate(raw_data)
        if fs is None:
            fs = cfg.DEFAULT_FS

    lines = raw_data.split('\n')
    in_ecg = False
    samples = []
    for line in lines:
        line = line.strip()
        if line == '[ECG]':
            in_ecg = True
            continue
        if line.startswith('['):
            in_ecg = False
            continue
        if in_ecg and ':' in line:
            data_part = line.split(':', 1)[1]
            try:
                samples.extend(int(v) for v in data_part.split(',') if v.strip())
            except ValueError:
                pass
    
    if clean and samples:
        return clean_ecg(samples, fs=fs)
    
    return samples


def clean_ecg(ecg_signal, fs, notch_freq=None, band_low=None, band_high=None):
    """
    Очистка ЭКГ: удаление выбросов и частотная фильтрация.
    """
    if notch_freq is None: notch_freq = cfg.NOTCH_FREQ
    if band_low is None: band_low = cfg.BANDPASS_LOW
    if band_high is None: band_high = cfg.BANDPASS_HIGH
    
    sig = np.asarray(ecg_signal, dtype=float).copy()
    if len(sig) < cfg.MIN_ECG_SAMPLES_TO_CLEAN:
        return sig
    
    q1, q3 = np.percentile(sig, [25, 75])
    iqr = q3 - q1
    lower = q1 - cfg.OUTLIER_IQR_MULTIPLIER * iqr
    upper = q3 + cfg.OUTLIER_IQR_MULTIPLIER * iqr
    outlier_mask = (sig < lower) | (sig > upper)
    if np.any(outlier_mask):
        sig[outlier_mask] = np.median(sig[~outlier_mask])
    
    sig = median_filter(sig, size=cfg.MEDIAN_FILTER_SIZE)
    
    nyq = 0.5 * fs
    padlen = min(3 * max(len(sig) // 10, 50), len(sig) - 1)
    
    if 0 < notch_freq < nyq:
        b_notch, a_notch = iirnotch(notch_freq / nyq, Q=cfg.NOTCH_Q)
        sig = filtfilt(b_notch, a_notch, sig, padlen=padlen)
    
    if 0 < band_low < band_high < nyq:
        b_band, a_band = butter(cfg.BUTTERWORTH_ORDER, [band_low / nyq, band_high / nyq], btype='band')
        sig = filtfilt(b_band, a_band, sig, padlen=padlen)
    
    return sig


def extract_rr_from_ecg(ecg_signal, fs, min_rr_ms=None, max_rr_ms=None):
    """
    Детекция R-пиков с правильными параметрами (фоллбек, если нет секции [RR]).
    """
    if min_rr_ms is None: min_rr_ms = cfg.MIN_RR_MS
    if max_rr_ms is None: max_rr_ms = cfg.MAX_RR_MS
    
    sig = np.asarray(ecg_signal, dtype=float)
    if len(sig) < cfg.MIN_ECG_SAMPLES_TO_CLEAN:
        return []
    
    min_distance_samples = int((min_rr_ms / 1000.0) * fs)
    prominence_val = np.ptp(sig) * cfg.PEAK_PROMINENCE_RATIO
    
    peaks, _ = signal.find_peaks(
        sig, 
        distance=min_distance_samples, 
        prominence=prominence_val
    )
    
    if len(peaks) < cfg.MIN_PEAKS_FOR_RR:
        return []
    
    rr_intervals_ms = np.diff(peaks) / fs * 1000.0
    
    valid_rr = []
    for i, rr in enumerate(rr_intervals_ms):
        if min_rr_ms <= rr <= max_rr_ms:
            valid_rr.append(rr)
        else:
            if valid_rr:
                valid_rr.append(np.median(valid_rr[-10:]))
            else:
                valid_rr.append(cfg.DEFAULT_RR_REPLACEMENT_MS)
    
    return valid_rr


def _status(mean_hr, rmssd):
    """Определяет, в пределах ли параметров анализа запись."""
    if mean_hr < cfg.HR_CRIT[0] or mean_hr > cfg.HR_CRIT[1] or rmssd < cfg.RMSSD_CRIT_THRESHOLD:
        return 'crit'
    if mean_hr < cfg.HR_WARN[0] or mean_hr > cfg.HR_WARN[1] or rmssd < cfg.RMSSD_WARN_THRESHOLD:
        return 'warn'
    return 'ok'


def filter_rr(rr, dev=None, min_rr=None, max_rr=None, window_size=None):
    if dev is None: dev = cfg.RR_FILTER_DEVIATION
    if min_rr is None: min_rr = cfg.MIN_RR_MS
    if max_rr is None: max_rr = cfg.MAX_RR_MS
    if window_size is None: window_size = cfg.RR_FILTER_WINDOW_SIZE
    
    if len(rr) < cfg.MIN_RR_TO_FILTER:
        return list(rr)
    
    clean = np.array(rr, dtype=float)
    half_win = window_size // 2
    
    outlier_mask = np.zeros_like(clean, dtype=bool)
    outlier_mask |= (clean < min_rr) | (clean > max_rr)
    
    for i in range(len(clean)):
        start = max(0, i - half_win)
        end = min(len(clean), i + half_win + 1)
        neighbors = clean[start:end]
        
        med = np.median(neighbors)
        
        if abs(clean[i] - med) > dev * med:
            outlier_mask[i] = True
            
    if np.any(outlier_mask):
        clean[outlier_mask] = np.nan
        nans = np.isnan(clean)
        if np.any(nans) and np.any(~nans):
            indices = np.arange(len(clean))
            clean[nans] = np.interp(indices[nans], indices[~nans], clean[~nans])
    
    return clean.tolist()