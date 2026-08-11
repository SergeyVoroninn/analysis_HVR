"""
Генератор записей ЭКГ в формате Polar H10 (TeamLogger).
Формирует файл с секциями [Header], [ECG], [RR], [ACC].

Использует профили качества из ecg_profiles.yaml.
"""

import os
import sys
import time
import math
import random
import yaml

# ============================================================
# ЗАГРУЗКА ПРОФИЛЕЙ
# ============================================================
PROFILES_PATH = os.path.join(os.path.dirname(__file__), "ecg_profiles.yaml")

def _load_active_profile() -> dict:
    """Загружает активный профиль из конфига."""
    if not os.path.exists(PROFILES_PATH):
        # Возвращаем дефолтные значения если конфига нет
        return _default_profile()
    
    with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    active_name = config.get('active_profile', 'default')
    profile = config.get('profiles', {}).get(active_name, {})
    
    # Если профиль пустой — используем дефолт
    if not profile:
        return _default_profile()
    
    return profile


def _default_profile() -> dict:
    """Возвращает дефолтные параметры профиля."""
    return {
        'transient_duration': 146,
        'transient_start_value': 13148,
        'transient_end_value': -150,
        'baseline_mean': -200,
        'baseline_respiratory_amplitude': 80,
        'baseline_respiratory_frequency': 0.05,
        'baseline_noise_range': [-15, 15],
        'heart_rate_period': 115,
        'p_wave': {'start': 0, 'end': 8, 'amplitude': 150},
        'q_wave': {'start': 10, 'end': 14, 'amplitude': -150},
        'r_wave': {'start': 14, 'end': 19, 'amplitude': 1300},
        's_wave': {'start': 19, 'end': 25, 'amplitude': -1400},
        't_wave': {'start': 35, 'end': 55, 'amplitude': 350},
    }


# ============================================================
# ГЕНЕРАЦИЯ ЭКГ
# ============================================================
def create_record(device='C8208E2E', datetime_str=None, duration_seconds=12.0,
                  profile_params=None, mean_rr_ms=None, rmssd_ms=None):
    """
    Генерирует полную запись ЭКГ в формате Polar H10.

    :param device: ID датчика Polar (например, 'C8208E2E')
    :param datetime_str: строка даты/времени в формате 'YYYY.MM.DD HH:MM:SS'
    :param duration_seconds: длительность записи в секундах
    :param profile_params: параметры профиля (если None — загружается активный)
    :return: строка с полным содержимым файла
    """
    if datetime_str is None:
        datetime_str = time.strftime("%Y.%m.%d %H:%M:%S", time.localtime())
    
    # Загружаем профиль если не передан
    if profile_params is None:
        profile_params = _load_active_profile()

    header = f"""TeamLoggerH10Data
[Header]
version=1.0
datetime={datetime_str}
polar_id={device}"""

    ecg_header = '[ECG]'
    ecg_data = create_ecg(duration_seconds, profile_params)

    rr_header = '[RR]'
    rr_data = create_rr(duration_seconds, mean_rr_ms, rmssd_ms)

    acc_header = '[ACC]'
    acc_data = create_acc(duration_seconds)

    return '\n'.join([header, ecg_header, ecg_data,
                      rr_header, rr_data, acc_header, acc_data])


def create_ecg(duration_seconds, profile_params=None):
    """
    Генерирует многострочный ЭКГ-сигнал на основе паттерна Polar H10.
    Частота дискретизации: 130 Гц.
    """
    # Это гарантирует, что калибровка работает.
    if profile_params is None:
        profile_params = _load_active_profile()
    
    polar_epoch = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, 0))
    start_timestamp = int((time.time() - polar_epoch) * 1e9)

    total_samples = int(duration_seconds * 130)
    samples_per_row = 73
    ns_per_row = int((samples_per_row / 130.0) * 1e9)

    ecg_rows = []
    current_timestamp = start_timestamp

    # Параметры из профиля
    transient_duration = profile_params.get('transient_duration', 146)
    transient_start = profile_params.get('transient_start_value', 13148)
    transient_end = profile_params.get('transient_end_value', -150)
    
    baseline_mean = profile_params.get('baseline_mean', -200)
    baseline_resp_amp = profile_params.get('baseline_respiratory_amplitude', 80)
    baseline_resp_freq = profile_params.get('baseline_respiratory_frequency', 0.05)
    noise_range = profile_params.get('baseline_noise_range', [-15, 15])
    
    heart_rate_period = profile_params.get('heart_rate_period', 115)
    
    p_wave = profile_params.get('p_wave', {'start': 0, 'end': 8, 'amplitude': 150})
    q_wave = profile_params.get('q_wave', {'start': 10, 'end': 14, 'amplitude': -150})
    r_wave = profile_params.get('r_wave', {'start': 14, 'end': 19, 'amplitude': 1300})
    s_wave = profile_params.get('s_wave', {'start': 19, 'end': 25, 'amplitude': -1400})
    t_wave = profile_params.get('t_wave', {'start': 35, 'end': 55, 'amplitude': 350})

    for row_idx in range(math.ceil(total_samples / samples_per_row)):
        row_values = []

        remaining_samples = total_samples - (row_idx * samples_per_row)
        current_row_samples = min(samples_per_row, remaining_samples)

        for s in range(current_row_samples):
            global_idx = row_idx * samples_per_row + s

            # 1. Стартовый переходный процесс
            if global_idx < transient_duration:
                progress = global_idx / transient_duration
                baseline = int(transient_start * (1 - progress) ** 2 + transient_end * progress)
            else:
                # Обычный дрейф изолинии с дыхательным шагом
                baseline = int(baseline_mean 
                              + baseline_resp_amp * math.sin(global_idx * baseline_resp_freq)
                              + random.randint(noise_range[0], noise_range[1]))

            # 2. Математическая модель сердцебиения (Комплекс P-Q-R-S-T)
            phase = global_idx % heart_rate_period
            heart_wave = 0

            if global_idx > 40:  # Не бьем во время экстремального старта
                if p_wave['start'] <= phase < p_wave['end']:
                    duration = p_wave['end'] - p_wave['start']
                    heart_wave = p_wave['amplitude'] * math.sin((phase - p_wave['start']) * (math.pi / duration))
                elif q_wave['start'] <= phase < q_wave['end']:
                    duration = q_wave['end'] - q_wave['start']
                    heart_wave = q_wave['amplitude'] * math.sin((phase - q_wave['start']) * (math.pi / duration))
                elif r_wave['start'] <= phase < r_wave['end']:
                    duration = r_wave['end'] - r_wave['start']
                    heart_wave = r_wave['amplitude'] * math.sin((phase - r_wave['start']) * (math.pi / duration))
                elif s_wave['start'] <= phase < s_wave['end']:
                    duration = s_wave['end'] - s_wave['start']
                    heart_wave = s_wave['amplitude'] * math.sin((phase - s_wave['start']) * (math.pi / duration))
                elif t_wave['start'] <= phase < t_wave['end']:
                    duration = t_wave['end'] - t_wave['start']
                    heart_wave = t_wave['amplitude'] * math.sin((phase - t_wave['start']) * (math.pi / duration))

            val = int(baseline + heart_wave)
            row_values.append(str(val))

        # Формируем строку
        if current_row_samples == samples_per_row:
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)},")
        else:
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)}")

        current_timestamp += ns_per_row

    return "\n".join(ecg_rows)


def create_rr(duration_seconds, mean_rr_ms=None, rmssd_ms=None):
    """
    Физиологичные RR: VLF+LF+HF полосы из нескольких компонент,
    дрейф частот (расширяет пики), амплитудная модуляция,
    транзиентные события (провалы/всплески как в реальных данных).
    """
    mean_rr = mean_rr_ms or 900
    rmssd = rmssd_ms or 70

    # --- Компоненты по полосам: (f_min, f_max, кол-во, доля амплитуды) ---
    bands = [
        (0.008, 0.035, 2, 1.0),   # VLF — медленные волны (красная полоса)
        (0.05,  0.12,  3, 0.7),   # LF  — несколько ритмов (жёлтая)
        (0.18,  0.35,  3, 0.9),   # HF  — дыхание с дрейфом (зелёная)
    ]
    comps = []
    for f_lo, f_hi, cnt, amp_share in bands:
        for _ in range(cnt):
            comps.append({
                'f':     random.uniform(f_lo, f_hi),
                'df':    random.uniform(-0.005, 0.005),   # дрейф частоты → широкий пик
                'phase': random.uniform(0, 2 * math.pi),
                'amp':   amp_share * rmssd * random.uniform(0.3, 0.5),
                'am_f':  random.uniform(0.004, 0.02),     # амплитудная модуляция
                'am_ph': random.uniform(0, 2 * math.pi),
            })

    noise_sd = 0.25 * rmssd

    # --- Транзиентные события (провалы/подъёмы, 2–4 за запись) ---
    events = []
    for _ in range(random.randint(2, 4)):
        events.append({
            't0':  random.uniform(20, max(40, duration_seconds - 40)),
            'dur': random.uniform(15, 50),
            'amp': random.uniform(-1.6, 1.6) * rmssd,
        })

    intervals = []
    acc = 0
    while acc < duration_seconds * 1000:
        t = acc / 1000.0
        val = mean_rr

        # Сумма ритмов: chirp (дрейф частоты) + амплитудная модуляция
        for c in comps:
            phase = 2 * math.pi * (c['f'] * t + 0.5 * c['df'] * t * t) + c['phase']
            mod = 0.6 + 0.4 * math.sin(2 * math.pi * c['am_f'] * t + c['am_ph'])
            val += c['amp'] * mod * math.sin(phase)

        # Транзиентные события — плавные горбы
        for e in events:
            if e['t0'] < t < e['t0'] + e['dur']:
                val += e['amp'] * math.sin(math.pi * (t - e['t0']) / e['dur'])

        val += random.gauss(0, noise_sd)
        val = max(0.5 * mean_rr, min(val, 1.5 * mean_rr))
        rr = int(round(val))
        intervals.append(str(rr))
        acc += rr

    return ",".join(intervals) 

def create_acc(duration_seconds):
    """
    Генерирует плоский массив ACC (акселерометр, 200 Гц).
    Базовое значение ~31500 с небольшим шумом.
    """
    count = int(duration_seconds * 200)
    acc_samples = [str(int(31500 + random.randint(-300, 300)))
                   for _ in range(count)]
    return ",".join(acc_samples)

if __name__ == '__main__':
    # Тест: генерируем одну запись ЭКГ
    test_record = create_record(
        device='TEST0001',
        datetime_str=time.strftime("%Y.%m.%d %H:%M:%S"),  # текущее время
        duration_seconds=300.0
    )

    with open('test_ecg_record.teamloggerh10', 'w', encoding='utf-8') as f:
        f.write(test_record)

    print("Тестовая запись сохранена в test_ecg_record.teamloggerh10")
    print(f"Размер: {len(test_record)} символов")

    # === АНАЛИЗ КАЧЕСТВА ===
    print(f"\n{'='*50}")
    print("Анализ качества ЭКГ")
    print('='*50)

    try:
        from calibrate_ecg import analyze_ecg_quality
        quality = analyze_ecg_quality(test_record)

        if quality:
            # Целевые метрики (из профиля default)
            target = {
                'min_snr': 15.0,
                'max_artifact_pct': 2.0,
                'max_baseline_drift': 50.0,
            }

            # === РАСЧЁТ SCORE В ПРОЦЕНТАХ ===
            snr = quality['snr']
            art = quality['artifact_pct']
            drift = quality['baseline_drift']

            # SNR: 0-40 баллов
            snr_t = target['min_snr']
            if snr >= snr_t:
                snr_score = 40 + min(20, (snr - snr_t) * 2)  # бонус до 60
            else:
                snr_score = max(0, 40 - (snr_t - snr) * 4)

            # Артефакты: 0-35 баллов
            art_t = target['max_artifact_pct']
            if art <= art_t:
                art_score = 35
            else:
                art_score = max(0, 35 - (art - art_t) * 7)

            # Дрейф: 0-25 баллов
            drift_t = target['max_baseline_drift']
            if drift <= drift_t:
                drift_score = 25
            else:
                drift_score = max(0, 25 - (drift - drift_t) * 0.5)

            total_score = min(100, max(0, snr_score + art_score + drift_score))

            # === ВЫВОД ===
            print(f"  Время записи:   {time.strftime('%Y.%m.%d %H:%M:%S')}")
            print(f"  SNR:            {snr:7.2f} дБ   (цель ≥{snr_t:.1f})   → {snr_score:5.1f}/60")
            print(f"  Артефакты:      {art:7.2f} %    (цель ≤{art_t:.1f}%) → {art_score:5.1f}/35")
            print(f"  Дрейф baseline: {drift:7.3f}     (цель ≤{drift_t:.1f})  → {drift_score:5.1f}/25")
            print(f"  Шум (σ):        {quality['noise_level']:7.3f}")
            print(f"  Длина сигнала:  {quality['analyzed_length']} отсчётов")

            if quality.get('rr_quality'):
                rr = quality['rr_quality']
                print(f"\n  RR-интервалы:")
                print(f"    Количество: {rr['count']}")
                print(f"    Mean RR:    {rr['mean_rr']:.1f} мс")
                print(f"    SDNN:       {rr['sdnn']:.2f} мс")
                print(f"    RMSSD:      {rr['rmssd']:.2f} мс")

            # === ИТОГОВЫЙ SCORE ===
            print(f"\n{'─'*50}")
            print(f"  КАЧЕСТВО: {total_score:5.1f}%")
            print(f"{'─'*50}")

            if total_score >= 80:
                print("✅ ОТЛИЧНО — данные готовы к анализу")
            elif total_score >= 60:
                print("⚠️  ХОРОШО — небольшие замечания")
            elif total_score >= 40:
                print("⚠️  УДОВЛЕТВОРИТЕЛЬНО — рекомендуется переснять")
            else:
                print("❌ ПЛОХО — необходимо переснять запись")
        else:
            print("⚠️  Не удалось проанализировать качество")

    except ImportError as e:
        print(f"⚠️  calibrate_ecg.py не найден: {e}")
    except Exception as e:
        print(f"⚠️  Ошибка анализа: {e}")