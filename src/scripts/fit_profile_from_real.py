"""
Создание профиля ЭКГ на основе реальной записи Polar H10.

Использование:
    python fit_profile_from_real.py "запись.txt" --name real_c8208e2e --activate
"""
import os
import argparse
import numpy as np
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_PATH = os.path.join(BASE_DIR, "ecg_profiles.yaml")


def _rolling_median(x, w):
    pad = w // 2
    xp = np.pad(x, pad, mode='edge')
    windows = np.lib.stride_tricks.sliding_window_view(xp, w)
    return np.median(windows, axis=1)


# ============================================================
# РАЗБОР ФАЙЛА
# ============================================================
def parse_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    section, signal, rr, header = None, [], [], {}
    for line in lines:
        s = line.strip()
        if s == '[ECG]': section = 'ECG'; continue
        if s == '[RR]':  section = 'RR';  continue
        if s == '[ACC]': section = 'ACC'; continue
        if s.startswith('['): section = None; continue

        if section is None and '=' in s:
            k, v = s.split('=', 1)
            header[k] = v
        elif section == 'ECG' and ':' in s:
            vals = s.split(':', 1)[1].rstrip(',').split(',')
            signal.extend(int(v) for v in vals if v.strip().lstrip('-').isdigit())
        elif section == 'RR':
            rr.extend(int(v) for v in s.split(',') if v.strip().isdigit())

    return np.array(signal, dtype=float), rr, header


# ============================================================
# ИЗВЛЕЧЕНИЕ ПАРАМЕТРОВ  (возвращает КОРТЕЖ: profile, hrv)
# ============================================================
def fit(signal, rr):
    p = {}

    # --- 1. Переходный процесс ---
    base = _rolling_median(signal, 231)
    med = float(np.median(base[500:2000]))
    near = np.where(np.abs(base - med) < 250)[0]
    tr_dur = int(max(50, near[0])) if len(near) else 146
    p['transient_duration'] = tr_dur
    p['transient_start_value'] = int(signal[0])
    p['transient_end_value'] = int(base[tr_dur]) if tr_dur < len(base) else int(med)

    # --- 2. Базовая линия / дыхание / шум ---
    work = signal[tr_dur:]
    base_w = base[tr_dur:]

    smooth = _rolling_median(base_w, 51)
    breath = smooth - float(np.median(smooth))
    p['baseline_mean'] = int(np.median(base_w))
    p['baseline_respiratory_amplitude'] = int(max(10, np.std(breath) * np.sqrt(2)))

    zc = int(np.sum(np.diff(np.sign(breath)) != 0))
    f = zc / (2.0 * len(breath))
    p['baseline_respiratory_frequency'] = round(float(2 * np.pi * f), 4)

    resid = work - base_w
    r_raw = np.where(resid > 500)[0]
    mask = np.zeros(len(work), bool)
    for q in r_raw:
        mask[max(0, q - 30):q + 70] = True
    noise_res = resid[~mask]
    mad = float(np.median(np.abs(noise_res - np.median(noise_res))))
    n = int(min(60, max(5, 2.5 * 1.4826 * mad)))
    p['baseline_noise_range'] = [-n, n]

    # --- 3. R-пики и период ---
    peaks = []
    for q in r_raw:
        if not peaks or q - peaks[-1] > 50:
            lo = max(0, q - 3)
            peaks.append(lo + int(np.argmax(work[lo:q + 4])))
    p['heart_rate_period'] = int(np.median(np.diff(peaks)))

    # --- 4. Усреднённый комплекс → амплитуды волн ---
    before, after = 40, 80
    segs = [work[q - before:q + after] for q in peaks
            if q - before >= 0 and q + after < len(work)]
    avg = np.mean(segs, axis=0)
    bc = float(np.median(avg))

    p['p_wave'] = {'start': 0,  'end': 8,  'amplitude': int(max(50,  np.max(avg[before-20:before-8]) - bc))}
    p['q_wave'] = {'start': 10, 'end': 14, 'amplitude': int(min(-50, np.min(avg[before-8:before-2]) - bc))}
    p['r_wave'] = {'start': 14, 'end': 19, 'amplitude': int(avg[before] - bc)}
    p['s_wave'] = {'start': 19, 'end': 25, 'amplitude': int(min(-100, np.min(avg[before+2:before+12]) - bc))}
    p['t_wave'] = {'start': 35, 'end': 55, 'amplitude': int(max(100, np.max(avg[before+18:before+50]) - bc))}
    p['target'] = {'min_snr': 15.0, 'max_artifact_pct': 2.0, 'max_baseline_drift': 50.0}

    # --- 5. ВРС спортсмена ---
    rr_arr = np.asarray(rr, dtype=float)
    hrv = {
        'mean_rr': float(np.mean(rr_arr)),
        'sdnn':    float(np.std(rr_arr)),
        'rmssd':   float(np.sqrt(np.mean(np.diff(rr_arr) ** 2))),
    }
    return p, hrv          # ← именно КОРТЕЖ из двух элементов


# ============================================================
# СОХРАНЕНИЕ
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', help='Реальная запись Polar H10')
    ap.add_argument('--name', default='real_sport')
    ap.add_argument('--activate', action='store_true')
    args = ap.parse_args()

    signal, rr, header = parse_file(args.file)
    profile, hrv = fit(signal, rr)
    profile['description'] = (f"Спортивный профиль по реальной записи "
                              f"{header.get('polar_id', '?')} от {header.get('datetime', '?')}")

    with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault('profiles', {})[args.name] = profile
    if args.activate:
        cfg['active_profile'] = args.name
    with open(PROFILES_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)  # safe_dump = без numpy-тегов

    print(f"✅ Профиль '{args.name}' сохранён в ecg_profiles.yaml\n")
    print("=== Извлечённые параметры сигнала ===")
    for k in ('transient_duration', 'transient_start_value', 'transient_end_value',
              'baseline_mean', 'baseline_respiratory_amplitude',
              'baseline_respiratory_frequency', 'baseline_noise_range', 'heart_rate_period'):
        print(f"  {k:35} = {profile[k]}")
    for w in ('p_wave', 'q_wave', 'r_wave', 's_wave', 't_wave'):
        print(f"  {w:35} = {profile[w]['amplitude']}")
    print("\n=== ВРС спортсмена (для карточки в БД) ===")
    print(f"  Mean RR  = {hrv['mean_rr']:.0f} мс  (ЧСС ≈ {60000 / hrv['mean_rr']:.0f} уд/мин)")
    print(f"  SDNN     = {hrv['sdnn']:.0f} мс")
    print(f"  RMSSD    = {hrv['rmssd']:.0f} мс  → hrv_rmssd_baseline")


if __name__ == '__main__':
    main()