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

# Границы анализа (уд/мин и мс)
HR_CRIT = (35, 200)    # выход за эти границы → красный
HR_WARN = (45, 180)    # выход за эти границы → жёлтый


def detect_sampling_rate(raw_data):
    """
    Пытается определить частоту дискретизации из метаданных файла.
    Возвращает fs в Гц или None, если не удалось определить.
    """
    lines = raw_data.split('\n')
    for line in lines[:50]:  # Проверяем первые 50 строк (метаданные обычно в начале)
        line_upper = line.strip().upper()
        if 'SAMPLE RATE' in line_upper or 'SAMPLING RATE' in line_upper or 'HZ' in line_upper or 'ГЦ' in line_upper:
            try:
                match = re.search(r'(\d+)', line)
                if match:
                    return float(match.group(1))
            except Exception:
                pass
    return None


def compute_psd(rr, fs=4.0, nperseg=None):
    """
    Спектральная плотность RR-тахограммы.
    """
    # 1. Фильтруем RR перед спектральным анализом
    rr_clean = filter_rr(rr)
    
    rr_arr = np.asarray(rr_clean, dtype=float)
    if len(rr_arr) < 4:
        return None, None, None

    # 2. Интерполяция на равномерную сетку
    t = np.cumsum(rr_arr) / 1000.0
    t_uniform = np.arange(t[0], t[-1], 1.0 / fs)
    x = np.interp(t_uniform, t, rr_arr)
    x = x - np.mean(x)

    # 3. Расчёт PSD через scipy
    if nperseg is None or nperseg > len(x):
        nperseg = len(x)
        
    freqs, psd = signal.welch(x, fs=fs, nperseg=nperseg, window='hann')

    # 4. Интегрирование по стандартным полосам (мс²)
    def band_power(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return float(trapezoid(psd[mask], freqs[mask]))

    bands = {
        "vlf": band_power(0.0033, 0.04),
        "lf":  band_power(0.04, 0.15),
        "hf":  band_power(0.15, 0.4),
    }
    bands["tp"] = bands["vlf"] + bands["lf"] + bands["hf"]
    
    return freqs, psd, bands


def stress_level(si):
    """Текстовый уровень стресса по индексу напряжения (Баевский)."""
    if si is None:
        return None
    if si < 30:   return "низкий"
    if si < 80:   return "умеренный"
    if si < 150:  return "высокий"
    return "перенапряжение"


def calc_stress(rr):
    """
    Расчёт индекса напряжения (SI = AMo / (Mo × MXDMN)).
    """
    # 1. Сначала фильтруем RR
    rr_clean = filter_rr(rr)
    
    if len(rr_clean) < 10:
        return None
    
    vals_sec = np.array(rr_clean) / 1000.0
    
    # 2. Устойчивая оценка размаха через перцентили 99 и 1
    p99, p1 = np.percentile(vals_sec, [99, 1])
    mxdmn = p99 - p1
    if mxdmn <= 0:
        return None

    # 3. Оценка моды через гистограмму
    mn, mx = np.min(vals_sec), np.max(vals_sec)
    bin_w = 0.05
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
    # Автоопределение частоты, если не передана явно
    if fs is None:
        fs = detect_sampling_rate(raw_data)
        if fs is None:
            fs = 130.0  # Fallback для Polar H10 / teamlogger
    
    lines = raw_data.split('\n')
    
    # 1. ПЕРВЫЙ ПРИОРИТЕТ: Читаем секцию [RR] (аппаратная детекция)
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
    
    # Если нашли достаточно интервалов, возвращаем их сразу!
    if len(rr) > 10:
        return rr

    # 2. Фоллбек: Если [RR] пуст или отсутствует, пытаемся извлечь из [ECG]
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
        
        if len(samples) > 100:
            ecg_clean = clean_ecg(samples, fs=fs)
            rr_from_ecg = extract_rr_from_ecg(ecg_clean, fs=fs)
            if rr_from_ecg and len(rr_from_ecg) > 10:
                return rr_from_ecg
    
    # Если ничего не получилось, возвращаем пустой список
    return rr


def calc_metrics(rr):
    """
    Расчёт метрик HRV с предварительной фильтрацией RR.
    """
    # 1. Фильтруем артефакты в RR
    rr_clean = filter_rr(rr)
    
    n = len(rr_clean)
    if n < 3:
        return None

    rr_array = np.array(rr_clean, dtype=float)
    mean_rr = np.mean(rr_array)
    
    # ddof=1 обеспечивает несмещённую оценку (деление на n-1)
    sdnn = np.std(rr_array, ddof=1)
    
    # RMSSD: квадратный корень из среднего квадратов разностей соседних интервалов
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
            fs = 130.0

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


def clean_ecg(ecg_signal, fs, notch_freq=50.0, band_low=0.5, band_high=40.0):
    """
    Очистка ЭКГ: удаление выбросов и частотная фильтрация.
    fs передаётся явно из вызывающей функции.
    """
    sig = np.asarray(ecg_signal, dtype=float).copy()
    if len(sig) < 100:
        return sig
    
    # 1. Удаление выбросов через IQR (до фильтрации!)
    q1, q3 = np.percentile(sig, [25, 75])
    iqr = q3 - q1
    lower = q1 - 3.0 * iqr
    upper = q3 + 3.0 * iqr
    outlier_mask = (sig < lower) | (sig > upper)
    if np.any(outlier_mask):
        sig[outlier_mask] = np.median(sig[~outlier_mask])
    
    # 2. Медианный фильтр (окно 5 семплов = ~38 мс при 130 Гц)
    sig = median_filter(sig, size=5)
    
    # 3. Частотные фильтры с контролируемым padlen
    nyq = 0.5 * fs
    padlen = min(3 * max(len(sig) // 10, 50), len(sig) - 1)
    
    if 0 < notch_freq < nyq:
        b_notch, a_notch = iirnotch(notch_freq / nyq, Q=30.0)
        sig = filtfilt(b_notch, a_notch, sig, padlen=padlen)
    
    if 0 < band_low < band_high < nyq:
        b_band, a_band = butter(4, [band_low / nyq, band_high / nyq], btype='band')
        sig = filtfilt(b_band, a_band, sig, padlen=padlen)
    
    return sig


def extract_rr_from_ecg(ecg_signal, fs, min_rr_ms=300, max_rr_ms=1500):
    """
    Детекция R-пиков с правильными параметрами (фоллбек, если нет секции [RR]).
    fs передаётся явно из вызывающей функции.
    """
    sig = np.asarray(ecg_signal, dtype=float)
    if len(sig) < 100:
        return []
    
    min_distance_samples = int((min_rr_ms / 1000.0) * fs)
    
    # prominence = 0.4 от полного размаха (баланс между шумом и пропусками)
    prominence_val = np.ptp(sig) * 0.4
    
    peaks, _ = signal.find_peaks(
        sig, 
        distance=min_distance_samples, 
        prominence=prominence_val
    )
    
    if len(peaks) < 2:
        return []
    
    rr_intervals_ms = np.diff(peaks) / fs * 1000.0
    
    # Агрессивная постобработка: удаление и замена невозможных RR
    valid_rr = []
    for i, rr in enumerate(rr_intervals_ms):
        if min_rr_ms <= rr <= max_rr_ms:
            valid_rr.append(rr)
        else:
            # Заменяем на медиану предыдущих валидных (или 800 мс по умолчанию)
            if valid_rr:
                valid_rr.append(np.median(valid_rr[-10:]))
            else:
                valid_rr.append(800.0)
    
    return valid_rr


def _status(mean_hr, rmssd):
    """Определяет, в пределах ли параметров анализа запись."""
    if mean_hr < HR_CRIT[0] or mean_hr > HR_CRIT[1] or rmssd < 5:
        return 'crit'
    if mean_hr < HR_WARN[0] or mean_hr > HR_WARN[1] or rmssd < 10:
        return 'warn'
    return 'ok'


def filter_rr(rr, dev=0.30, min_rr=300, max_rr=2000):
    """
    Корректирует артефактные RR, заменяя их на предыдущее валидное значение.
    """
    if len(rr) < 10:
        return list(rr)
    
    clean = np.array(rr, dtype=float)
    
    for i in range(1, len(clean)):
        prev = clean[i-1]
        current = clean[i]
        
        if not (min_rr <= current <= max_rr):
            clean[i] = prev
        elif abs(current - prev) > dev * prev:
            clean[i] = prev
            
    return clean.tolist()