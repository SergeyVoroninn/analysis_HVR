"""
Анализ ЭКГ: парсинг сырых данных и расчёт метрик HRV.
Используется и при генерации БД, и в приложении.
"""

import math
import numpy as np

# Границы анализа (уд/мин и мс)
HR_CRIT = (35, 200)    # выход за эти границы → красный
HR_WARN = (45, 180)    # выход за эти границы → жёлтый


def compute_psd(rr, fs=4.0, nperseg=None):
    """
    Спектральная плотность RR-тахограммы.
    По умолчанию — периодограмма по ВСЕЙ записи (как в Омеге),
    иначе Вельч с заданным nperseg.
    """
    rr = np.asarray(rr, dtype=float)

    t = np.cumsum(rr) / 1000.0
    t_uniform = np.arange(t[0], t[-1], 1.0 / fs)
    x = np.interp(t_uniform, t, rr)
    x = x - np.mean(x)

    if nperseg is None or nperseg > len(x):
        nperseg = len(x)          # ← один сегмент = вся запись

    window = np.hanning(nperseg)
    ...  # остальное без изменений
    win_norm = fs * np.sum(window ** 2)
    step = nperseg // 2

    segs = []
    for i in range(0, len(x) - nperseg + 1, step):
        seg = x[i:i + nperseg] * window
        X = np.fft.rfft(seg)
        p = np.abs(X) ** 2 / win_norm
        p[1:] *= 2
        segs.append(p)

    if not segs:  # сигнал короче одного сегмента
        x = np.pad(x, (0, nperseg - len(x)))
        X = np.fft.rfft(x * window)
        p = np.abs(X) ** 2 / win_norm
        p[1:] *= 2
        segs = [p]

    freqs = np.fft.rfftfreq(nperseg, 1.0 / fs)
    psd = np.mean(segs, axis=0)

    def bp(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        trapz = getattr(np, "trapezoid", None) or np.trapz
        return float(trapz(psd[m], freqs[m]))

    bands = {
        "vlf": bp(0.0033, 0.04),
        "lf":  bp(0.04, 0.15),
        "hf":  bp(0.15, 0.4),
    }
    bands["tp"] = bands["vlf"] + bands["lf"] + bands["hf"]
    return freqs, psd, bands

def stress_level(si):
    """Текстовый уровень стресса по индексу."""
    if si is None:
        return None
    if si < 30:   return "низкий"
    if si < 80:   return "умеренный"
    if si < 150:  return "высокий"
    return "перенапряжение"

def calc_stress(rr):
    if len(rr) < 10:
        return None
    
    vals_sec = np.array(rr) / 1000.0
    
    # Использовать перцентили вместо min/max для устойчивости к артефактам
    p95 = np.percentile(vals_sec, 95)
    p5 = np.percentile(vals_sec, 5)
    mxdmn = p95 - p5
    
    if mxdmn <= 0:
        return None

    mn, mx = min(vals_sec), max(vals_sec)
    bin_w = 0.05
    nbins = int((mx - mn) // bin_w) + 1
    hist = [0] * nbins
    for v in vals_sec:
        hist[min(int((v - mn) / bin_w), nbins - 1)] += 1

    max_count = max(hist)
    mode_idx = hist.index(max_count)
    mo = mn + (mode_idx + 0.5) * bin_w
    amo = max_count / len(vals_sec) * 100.0
    
    si = amo / (mo * mxdmn)

    return {"si": si, "amo": amo, "mo_ms": mo * 1000,
            "mxdmn_ms": mxdmn * 1000, "level": stress_level(si)}

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
    if len(rr) < 3:
        return None
    rr = filter_rr(rr)
    if len(rr) < 3:
        return None

    n = len(rr)
    mean_rr = sum(rr) / n
    sdnn = math.sqrt(sum((x - mean_rr) ** 2 for x in rr) / (n - 1))
    diffs = [rr[i + 1] - rr[i] for i in range(n - 1)]
    rmssd = math.sqrt(sum(d * d for d in diffs) / len(diffs))

    mean_hr = 60000 / mean_rr
    status = _status(mean_hr, rmssd)

    return {
        "mean_hr": mean_hr,
        "min_hr": 60000 / max(rr),
        "max_hr": 60000 / min(rr),
        "mean_rr": mean_rr,
        "sdnn": sdnn,
        "rmssd": rmssd,
        "count": n,
        "status": status,
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
    
    clean = list(rr)
    
    for i in range(1, len(clean)):
        prev = clean[i-1]
        current = clean[i]
        
        if not (min_rr <= current <= max_rr):
            clean[i] = prev
            continue
            
        if abs(current - prev) > dev * prev:
            clean[i] = prev
            
    return clean