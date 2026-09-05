"""
Анализ ЭКГ: парсинг сырых данных и расчёт метрик HRV.
Используется и при генерации БД, и в приложении.

Зависимости: numpy, scipy
Установка: pip install numpy scipy
"""

import numpy as np
from scipy import signal
from scipy.integrate import trapezoid

# Границы анализа (уд/мин и мс)
HR_CRIT = (35, 200)    # выход за эти границы → красный
HR_WARN = (45, 180)    # выход за эти границы → жёлтый


def compute_psd(rr, fs=4.0, nperseg=None):
    """
    Спектральная плотность RR-тахограммы.
    Использует метод Уэлча (scipy.signal.welch) для надёжного и быстрого расчёта.
    """
    rr = np.asarray(rr, dtype=float)
    if len(rr) < 4:
        return None, None, None

    # 1. Интерполяция на равномерную сетку
    t = np.cumsum(rr) / 1000.0
    t_uniform = np.arange(t[0], t[-1], 1.0 / fs)
    x = np.interp(t_uniform, t, rr)
    x = x - np.mean(x)

    # 2. Расчёт PSD через scipy
    if nperseg is None or nperseg > len(x):
        nperseg = len(x)
        
    freqs, psd = signal.welch(x, fs=fs, nperseg=nperseg, window='hann')

    # 3. Интегрирование по стандартным полосам (мс²)
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
    Использует перцентили 95 и 05 для устойчивой оценки размаха (MXDMN).
    """
    if len(rr) < 10:
        return None
    
    vals_sec = np.array(rr) / 1000.0
    
    # Устойчивая оценка размаха через перцентили (защита от выбросов)
    p95, p5 = np.percentile(vals_sec, [95, 5])
    mxdmn = p95 - p5
    if mxdmn <= 0:
        return None

    # Оценка моды через гистограмму
    mn, mx = np.min(vals_sec), np.max(vals_sec)
    bin_w = 0.05
    counts, bin_edges = np.histogram(vals_sec, bins=np.arange(mn, mx + bin_w, bin_w))
    
    max_count = np.max(counts)
    mode_idx = np.argmax(counts)
    mo = bin_edges[mode_idx] + 0.5 * bin_w  # середина модального интервала
    
    amo = (max_count / len(vals_sec)) * 100.0
    si = amo / (mo * mxdmn)

    return {
        "si": float(si), 
        "amo": float(amo), 
        "mo_ms": float(mo * 1000),
        "mxdmn_ms": float(mxdmn * 1000), 
        "level": stress_level(si)
    }


def parse_rr(raw_data):
    """Извлекает RR-интервалы (мс) из сырой записи."""
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
    return rr


def calc_metrics(rr):
    """Расчёт базовых временных метрик HRV через векторизованные операции numpy."""
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


def parse_ecg(raw_data):
    """Извлекает семплы сигнала ЭКГ из сырой записи."""
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
    return samples


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