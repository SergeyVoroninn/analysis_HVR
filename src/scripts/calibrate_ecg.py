"""
Скрипт автоматической калибровки качества ЭКГ.

Генерирует тестовые ЭКГ, анализирует качество и подбирает
оптимальные коэффициенты для достижения целевых метрик.

Использование:
    python calibrate_ecg.py                    # калибровка активного профиля
    python calibrate_ecg.py --profile high     # калибровка конкретного профиля
    python calibrate_ecg.py --all              # калибровка всех профилей
"""

import os
import sys
import yaml
import random
import argparse
import numpy as np
from typing import Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from ecg_generator import create_record
from analysis import parse_rr, calc_metrics


# ============================================================
# ЗАГРУЗКА И СОХРАНЕНИЕ ПРОФИЛЕЙ
# ============================================================
def load_profiles(config_path: str = "ecg_profiles.yaml") -> Dict:
    if not os.path.exists(config_path):
        print(f"❌ Файл профилей не найден: {config_path}")
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_profiles(profiles: Dict, config_path: str = "ecg_profiles.yaml"):
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(profiles, f, allow_unicode=True, sort_keys=False, indent=2)
    print(f"✅ Профили сохранены в {config_path}")


def _rolling_median(x, w):
    pad = w // 2
    xp = np.pad(x, pad, mode='edge')
    windows = np.lib.stride_tricks.sliding_window_view(xp, w)
    return np.median(windows, axis=1)


def analyze_ecg_quality(raw_str: str, skip_transient: int = 200,
                        heart_period: int = 115) -> Dict:
    """
    Качество чистого baseline: сердечные комплексы (P..T) полностью
    маскируются и интерполируются, остаются только дыхание + шум.
    """
    lines = raw_str.split('\n')
    ecg_start = ecg_end = None
    for i, line in enumerate(lines):
        if line.strip() == '[ECG]':
            ecg_start = i + 1
        elif line.strip().startswith('[') and ecg_start is not None:
            ecg_end = i
            break
    if ecg_start is None:
        return None

    signal = []
    for line in lines[ecg_start:ecg_end]:
        if ':' in line:
            vals = line.split(':', 1)[1].rstrip(',').split(',')
            signal.extend([int(v) for v in vals if v])
    if not signal:
        return None

    signal = np.array(signal[skip_transient:], dtype=float)
    n = len(signal)
    if n < 500:
        return None

    # Robust baseline для детекции R-пиков
    base = _rolling_median(signal, 2 * heart_period + 1)
    residual = signal - base

    # R-пики и маска ВСЕГО комплекса (P начинается ~за 25 до R, T кончается ~+60)
    r_peaks = np.where(residual > 500)[0]
    full_mask = np.zeros(n, bool)
    for p in r_peaks:
        full_mask[max(0, p - 25):min(n, p + 60)] = True

    # Интерполяция комплексов -> непрерывный чистый baseline
    idx = np.arange(n)
    good = ~full_mask
    if good.sum() < 200:
        return None
    interp = np.interp(idx, idx[good], signal[good])

    # Дыхание = сглаженный interp; шум = остаток
    smooth = _rolling_median(interp, 51)
    noise_res = interp - smooth
    noise_var = np.var(noise_res)
    noise_std = np.sqrt(noise_var) if noise_var > 0 else 1.0

    breath = smooth - np.median(smooth)
    breath_var = np.var(breath)
    drift = np.std(breath)

    snr = 10 * np.log10(breath_var / noise_var) if noise_var > 0 else 99.0

    art_thr = max(30, 3 * noise_std)
    artifact_pct = float(np.mean(np.abs(noise_res) > art_thr) * 100)

    # === ИСПРАВЛЕНО: используем уже импортированные функции ===
    rr = parse_rr(raw_str)
    rr_quality = None
    if rr:
        m = calc_metrics(rr)
        rr_quality = {'count': len(rr), 'mean_rr': m.get('mean_rr'),
                      'sdnn': m.get('sdnn'), 'rmssd': m.get('rmssd')}

    return {
        'snr': round(snr, 2),
        'artifact_pct': round(artifact_pct, 2),
        'baseline_drift': round(drift, 3),
        'noise_level': round(noise_std, 3),
        'signal_length': n + skip_transient,
        'analyzed_length': n,
        'rr_quality': rr_quality,
    }

# ============================================================
# АДАПТИВНАЯ КАЛИБРОВКА
# ============================================================
def _adapt_profile(profile: Dict, quality: Dict, target: Dict) -> Dict:
    p = profile.copy()
    snr_t = target.get('min_snr', 15)
    art_t = target.get('max_artifact_pct', 2)
    drift_t = target.get('max_baseline_drift', 50)

    drift, snr, art = (quality['baseline_drift'], quality['snr'],
                       quality['artifact_pct'])
    noise = p.get('baseline_noise_range', [-15, 15])
    breath_amp = p.get('baseline_respiratory_amplitude', 80)

    # Приоритет: сначала дрейф, потом артефакты, потом SNR

    # 1) Дрейф слишком высокий → гасим дыхание
    if drift > drift_t:
        p['baseline_respiratory_amplitude'] = max(15, int(breath_amp * 0.8))
        print(f"    ↘ Дрейф {drift:.1f}: дыхание ×0.8")

    # 2) Артефакты → гасим шум
    elif art > art_t:
        p['baseline_noise_range'] = [int(noise[0] * 0.7), int(noise[1] * 0.7)]
        print(f"    ↘ Артефакты {art:.2f}%: шум ×0.7")

    # 3) SNR низкий → усиливаем дыхание (если дрейф позволяет) и гасим шум
    elif snr < snr_t:
        if drift < drift_t * 0.7:
            p['baseline_respiratory_amplitude'] = min(120, int(breath_amp * 1.15))
            print(f"    ↗ SNR {snr:.1f}: дыхание ×1.15")
        p['baseline_noise_range'] = [int(noise[0] * 0.75), int(noise[1] * 0.75)]
        print(f"    ↘ SNR: шум ×0.75")

    # 4) Всё ок → лёгкая доводка
    else:
        if abs(noise[0]) > 5:
            p['baseline_noise_range'] = [int(noise[0] * 0.9), int(noise[1] * 0.9)]
        print(f"    ✓ Всё в норме, доводка шума")

    return p


def _compute_score(quality: Dict, target: Dict) -> float:
    """Вычисляет интегральный score качества (0-100)."""
    score = 0

    # SNR (до 40 баллов)
    snr_target = target.get('min_snr', 15)
    snr = quality['snr']
    if snr >= snr_target:
        score += 40 + min(20, (snr - snr_target) * 2)
    else:
        score += max(0, 40 - (snr_target - snr) * 4)

    # Артефакты (до 35 баллов)
    art_target = target.get('max_artifact_pct', 2)
    art = quality['artifact_pct']
    if art <= art_target:
        score += 35
    else:
        score += max(0, 35 - (art - art_target) * 7)

    # Дрейф (до 25 баллов)
    drift_target = target.get('max_baseline_drift', 50)
    drift = quality['baseline_drift']
    if drift <= drift_target:
        score += 25
    else:
        score += max(0, 25 - (drift - drift_target) * 0.5)

    return min(100, max(0, score))


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ КАЛИБРОВКИ
# ============================================================
def calibrate_profile(profile_name: str, profiles: Dict,
                      iterations: int = 15, duration: float = 15.0) -> Dict:
    print(f"\n{'='*60}")
    print(f"Калибровка профиля: {profile_name}")
    print('='*60)

    profile = profiles['profiles'][profile_name]
    target = profile.get('target', {})

    best_quality = None
    best_score = -1
    best_profile = profile.copy()

    for i in range(iterations):
        print(f"\nИтерация {i+1}/{iterations}...")

        raw_str = create_record(
            device='CALIBRATION',
            datetime_str='2026.08.10 12:00:00',
            duration_seconds=duration,
            profile_params=profile,
        )

        quality = analyze_ecg_quality(raw_str)
        if quality is None:
            print("  ❌ Не удалось проанализировать")
            continue

        score = _compute_score(quality, target)

        print(f"  SNR:     {quality['snr']:6.2f} дБ  (цель: ≥{target.get('min_snr', 15)})")
        print(f"  Арт-ты:  {quality['artifact_pct']:5.2f}%   (цель: ≤{target.get('max_artifact_pct', 2)}%)")
        print(f"  Дрейф:   {quality['baseline_drift']:6.2f}    (цель: ≤{target.get('max_baseline_drift', 50)})")
        print(f"  ⭐ Score: {score:.1f}/100")

        if score > best_score:
            best_score = score
            best_quality = quality.copy()
            best_profile = profile.copy()
            print("  ✅ Новый лучший результат")

        # Все цели достигнуты — выход
        if (quality['snr'] >= target.get('min_snr', 15)
                and quality['artifact_pct'] <= target.get('max_artifact_pct', 2)
                and quality['baseline_drift'] <= target.get('max_baseline_drift', 50)):
            print("\n  🎉 Все целевые метрики достигнуты!")
            break

        # Адаптируем профиль
        profile = _adapt_profile(profile, quality, target)

    print(f"\n{'='*60}")
    print(f"Результат калибровки: {profile_name}")
    print('='*60)
    print(f"Лучший score: {best_score:.1f}/100")
    if best_quality:
        print(f"  SNR:     {best_quality['snr']:.2f} дБ")
        print(f"  Арт-ты:  {best_quality['artifact_pct']:.2f}%")
        print(f"  Дрейф:   {best_quality['baseline_drift']:.2f}")

    return best_profile


def main():
    parser = argparse.ArgumentParser(description='Калибровка качества ЭКГ')
    parser.add_argument('--profile', type=str, help='Имя профиля')
    parser.add_argument('--all', action='store_true', help='Калибровать все')
    parser.add_argument('--iterations', type=int, default=15)
    parser.add_argument('--duration', type=float, default=15.0)

    args = parser.parse_args()
    profiles = load_profiles()

    if args.all:
        names = list(profiles['profiles'].keys())
    elif args.profile:
        names = [args.profile]
    else:
        names = [profiles.get('active_profile', 'default')]

    for name in names:
        if name not in profiles['profiles']:
            print(f"❌ Профиль '{name}' не найден")
            continue

        updated = calibrate_profile(name, profiles,
                                    iterations=args.iterations,
                                    duration=args.duration)
        profiles['profiles'][name] = updated

    save_profiles(profiles)
    print(f"\n✅ Калибровка завершена!")


if __name__ == '__main__':
    main()