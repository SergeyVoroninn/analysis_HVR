"""
Анализ ЭКГ: парсинг сырых данных и расчёт метрик HRV.
Используется и при генерации БД, и в приложении.
"""

import math
import numpy as np
from scipy.interpolate import CubicSpline
# Границы анализа (уд/мин и мс)
HR_CRIT = (35, 200)    # выход за эти границы → красный
HR_WARN = (45, 180)    # выход за эти границы → жёлтый


def compute_psd(rr, fs=4.0, nperseg=256):
    """
    Считает спектральную плотность мощности RR-тахограммы (метод Вельча).

    :param rr: список RR-интервалов (мс)
    :param fs: частота ресемплинга (Гц)
    :param nperseg: длина сегмента Вельча
    :return: (freqs, psd, bands) где bands = {vlf, lf, hf, tp} в мс^2
    """
    R_R = np.asarray(rr, dtype=float)

    ####
    # BLOCK в котором отрезают начало записи и конец
    ####
    start = int(len(R_R) * 0.1)
    stop = int(len(R_R) * 0.9)
    R_R = R_R[start:stop]

    #Переводим в секунды кардиоинтерваллограмму
    R_R_sec = R_R / 1000
    #Интерполяция:
    #1. высчитываем временную шкалу
    time_steps = np.cumsum(R_R_sec)
    #2. Делаем шкалу с частотой дискретизации 0.25
    new_time = np.arange(time_steps[0], time_steps[-1], 0.25)
    #3. используем для отображения на новую шкалу кубическую интерполяцию
    spline_model = CubicSpline(time_steps, R_R_sec)
    R_R_interp = spline_model(new_time)
    #Центрирование данных
    R_R_centered = R_R_interp - np.mean(R_R_interp)

    ### Ритмограмма R-R Интерполированные Аппаратные данные

    ### Переход из частотной во временную область
    R_R_spectral = np.fft.fft(R_R_centered)

    #Задаём частоту дискретизации и преобразовываем ось
    fs = 4
    frequencies = np.fft.fftfreq(len(R_R_interp), d=1/fs)  # d — интервал дискретизации (1/fs)
    frequencies[:10]
    #Спектр (15) является зеркально симметричным (двусторонним) относительно своей центральной точки l=(N-l)/2, то есть: Xi=XN-i поэтому для его графического отображения и последующего исследования достаточно первых (N-l)/2 амплитуд (односторонний спектр). При переходе от двустороннего спектра к одностороннему необходимо нормирование его амплитуд умножением на √2 (нормировка спектра мощности производится умножением на 2)
    #Мощность спектра
    #$$ PSD(f)=\frac{2\cdot |z|{}^{2}}{f_{s}\cdot N}$$
    N_interp = len(R_R_interp)
    #Мощность спектра в секундах
    psd_sec = 2 * np.abs(R_R_spectral) ** 2 / (fs *N_interp)  
    #Мощность спектра в милисекундах
    psd= psd_sec* 1000000
    #Маска для нижних  частот (в которых работает наше тело?)
    low_freq_mask = (frequencies > 0) & (frequencies < 0.4)

    #Маски для каждой категории частот:
    hf_mask = (frequencies > 0.15) & (frequencies <= 0.4)
    lf_mask = (frequencies > 0.04) & (frequencies <= 0.15)
    vlf_mask = (frequencies > 0.003) & (frequencies <= 0.04)
    ulf_mask = (frequencies > 0) & (frequencies <= 0.003)

    ### Расчёт совокупной мощности спектра
    hf = np.trapz(psd[hf_mask], frequencies[hf_mask])
    lf = np.trapz(psd[lf_mask], frequencies[lf_mask])
    vlf = np.trapz(psd[vlf_mask], frequencies[vlf_mask])
    ulf = np.trapz(psd[ulf_mask], frequencies[ulf_mask])
    bands = {
        'hf':hf,
        'lf':lf,
        'vlf':vlf,
        'ulf':ulf,
        'tp':(hf+lf+vlf+ulf)
    }
    return frequencies, psd, bands

def stress_level(si):
    """Текстовый уровень стресса по индексу."""
    if si is None:
        return None
    if si < 30:   return "низкий"
    if si < 80:   return "умеренный"
    if si < 150:  return "высокий"
    return "перенапряжение"


def calc_stress(rr):
    """Индекс стресса (ИС) по Баевскому: ИС = AMo / (2*Mo*MxDMn)."""
    if len(rr) < 10:
        return None
    vals = [r / 1000.0 for r in rr]
    mn, mx = min(vals), max(vals)
    mxdmn = mx - mn
    if mxdmn <= 0:
        return None

    bin_w = 0.05
    nbins = int(mxdmn // bin_w) + 1
    hist = [0] * nbins
    for v in vals:
        hist[min(int((v - mn) / bin_w), nbins - 1)] += 1

    max_count = max(hist)
    mode_idx = hist.index(max_count)
    mo = mn + (mode_idx + 0.5) * bin_w
    amo = max_count / len(vals) * 100.0
    si = amo / (2 * mo * mxdmn)

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
    """Считает метрики HRV и определяет статус записи."""
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