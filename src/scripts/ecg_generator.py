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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(BASE_DIR)  # путь к src/
sys.path.insert(0, SRC_DIR)

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
    if datetime_str is None:
        datetime_str = time.strftime("%Y.%m.%d %H:%M:%S", time.localtime())

    if profile_params is None:
        profile_params = _load_active_profile()

    header = f"""TeamLoggerH10Data
[Header]
version=1.0
datetime={datetime_str}
polar_id={device}"""

    # === ЕДИНЫЙ источник RR: секция [RR] и R-пики в ЭКГ согласованы ===
    rr_list = create_rr_list(duration_seconds, mean_rr_ms, rmssd_ms)

    ecg_header = '[ECG]'
    ecg_data = create_ecg(duration_seconds, profile_params, rr_intervals=rr_list)

    rr_header = '[RR]'
    rr_data = ",".join(str(v) for v in rr_list)

    acc_header = '[ACC]'
    acc_data = create_acc(duration_seconds)

    return '\n'.join([header, ecg_header, ecg_data,
                      rr_header, rr_data, acc_header, acc_data])

def create_ecg(duration_seconds, profile_params=None, rr_intervals=None):
    """
    Генерирует ЭКГ. Если передан rr_intervals — R-пики ставятся точно
    по накопленным RR (согласование с секцией [RR]).
    """
    if profile_params is None:
        profile_params = _load_active_profile()

    polar_epoch = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, 0))
    start_timestamp = int((time.time() - polar_epoch) * 1e9)

    total_samples = int(duration_seconds * 130)
    samples_per_row = 73
    ns_per_row = int((samples_per_row / 130.0) * 1e9)

    # Параметры профиля
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

    # --- 1. Базовая линия для всех отсчётов ---
    signal = [0.0] * total_samples
    for idx in range(total_samples):
        if idx < transient_duration:
            progress = idx / transient_duration
            signal[idx] = transient_start * (1 - progress) ** 2 + transient_end * progress
        else:
            signal[idx] = (baseline_mean
                           + baseline_resp_amp * math.sin(idx * baseline_resp_freq)
                           + random.randint(noise_range[0], noise_range[1]))

    # --- 2. Сетка R-пиков ---
    if rr_intervals:
        # R-пики по накопленным RR (мс → отсчёты @130 Гц)
        r_positions = []
        acc = 0
        for rr in rr_intervals:
            acc += int(round(rr * 130 / 1000.0))
            if acc < total_samples:
                r_positions.append(acc)
    else:
        # Фолбэк: фиксированный период (старое поведение)
        r_positions = list(range(heart_rate_period, total_samples, heart_rate_period))

    R_OFFSET = 16      # вершина R находится на фазе ~16 от начала комплекса
    COMPLEX_LEN = 56   # P(0)..T(55)

    def wave(phase):
        if p_wave['start'] <= phase < p_wave['end']:
            d = p_wave['end'] - p_wave['start']
            return p_wave['amplitude'] * math.sin((phase - p_wave['start']) * math.pi / d)
        if q_wave['start'] <= phase < q_wave['end']:
            d = q_wave['end'] - q_wave['start']
            return q_wave['amplitude'] * math.sin((phase - q_wave['start']) * math.pi / d)
        if r_wave['start'] <= phase < r_wave['end']:
            d = r_wave['end'] - r_wave['start']
            return r_wave['amplitude'] * math.sin((phase - r_wave['start']) * math.pi / d)
        if s_wave['start'] <= phase < s_wave['end']:
            d = s_wave['end'] - s_wave['start']
            return s_wave['amplitude'] * math.sin((phase - s_wave['start']) * math.pi / d)
        if t_wave['start'] <= phase < t_wave['end']:
            d = t_wave['end'] - t_wave['start']
            return t_wave['amplitude'] * math.sin((phase - t_wave['start']) * math.pi / d)
        return 0.0

    # --- 3. Накладываем комплексы на сетку R-пиков ---
    for r_pos in r_positions:
        start = r_pos - R_OFFSET
        if start < 40:                      # не бьём во время переходного процесса
            continue
        for phase in range(COMPLEX_LEN):
            idx = start + phase
            if idx >= total_samples:
                break
            signal[idx] += wave(phase)

    # --- 4. Форматирование строк ---
    ecg_rows = []
    current_timestamp = start_timestamp
    for row_idx in range(math.ceil(total_samples / samples_per_row)):
        begin = row_idx * samples_per_row
        end = min(begin + samples_per_row, total_samples)
        row_values = [str(int(signal[i])) for i in range(begin, end)]

        if end - begin == samples_per_row:
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)},")
        else:
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)}")
        current_timestamp += ns_per_row

    return "\n".join(ecg_rows)

def create_rr_list(duration_seconds, mean_rr_ms=None, rmssd_ms=None):
    """
    Возвращает список RR-интервалов (мс) — единый источник для [RR] и ЭКГ.
    """
    mean_rr = mean_rr_ms or 900
    rmssd = rmssd_ms or 70

    intervals = []
    acc = 0
    phase_resp = random.uniform(0, 2 * math.pi)
    phase_slow = random.uniform(0, 2 * math.pi)

    resp_amp = 0.6 * rmssd
    slow_amp = 1.2 * rmssd
    noise_sd = 0.35 * rmssd

    while acc < duration_seconds * 1000:
        t = acc / 1000.0
        resp = resp_amp * math.sin(2 * math.pi * 0.25 * t + phase_resp)
        slow = slow_amp * math.sin(2 * math.pi * 0.04 * t + phase_slow)
        noise = random.gauss(0, noise_sd)

        rr = mean_rr + resp + slow + noise
        rr = max(0.5 * mean_rr, min(rr, 1.5 * mean_rr))
        rr_int = int(round(rr))
        intervals.append(rr_int)
        acc += rr_int

    return intervals


def create_rr(duration_seconds, mean_rr_ms=None, rmssd_ms=None):
    """Строка RR для секции [RR] (для совместимости)."""
    return ",".join(str(v) for v in create_rr_list(duration_seconds, mean_rr_ms, rmssd_ms))

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
        datetime_str=time.strftime("%Y.%m.%d %H:%M:%S"),
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
        from analysis import parse_rr, calc_metrics, calc_stress, stress_level
        
        quality = analyze_ecg_quality(test_record)

        if quality:
            target = {
                'min_snr': 15.0,
                'max_artifact_pct': 2.0,
                'max_baseline_drift': 50.0,
            }

            snr = quality['snr']
            art = quality['artifact_pct']
            drift = quality['baseline_drift']

            # === РАСЧЁТ SCORE ===
            snr_t = target['min_snr']
            snr_score = 40 + min(20, (snr - snr_t) * 2) if snr >= snr_t else max(0, 40 - (snr_t - snr) * 4)

            art_t = target['max_artifact_pct']
            art_score = 35 if art <= art_t else max(0, 35 - (art - art_t) * 7)

            drift_t = target['max_baseline_drift']
            drift_score = 25 if drift <= drift_t else max(0, 25 - (drift - drift_t) * 0.5)

            total_score = min(100, max(0, snr_score + art_score + drift_score))

            # === ВЫВОД КАЧЕСТВА СИГНАЛА ===
            print(f"  Время записи:   {time.strftime('%Y.%m.%d %H:%M:%S')}")
            print(f"  SNR:            {snr:7.2f} дБ   (цель ≥{snr_t:.1f})   → {snr_score:5.1f}/60")
            print(f"  Артефакты:      {art:7.2f} %    (цель ≤{art_t:.1f}%) → {art_score:5.1f}/35")
            print(f"  Дрейф baseline: {drift:7.3f}     (цель ≤{drift_t:.1f})  → {drift_score:5.1f}/25")
            print(f"  Шум (σ):        {quality['noise_level']:7.3f}")
            print(f"  Длина сигнала:  {quality['analyzed_length']} отсчётов")

            # === ПОЛНЫЙ АНАЛИЗ ВРС ===
            rr = parse_rr(test_record)
            if rr and len(rr) > 10:
                metrics = calc_metrics(rr)
                stress = calc_stress(rr)
                
                print(f"\n{'─'*50}")
                print("  Метрики вариабельности сердечного ритма")
                print(f"{'─'*50}")
                
                # Основные параметры
                print(f"  Mean HR:        {metrics.get('mean_hr', 0):7.1f} уд/мин")
                print(f"  Mean RR:        {metrics.get('mean_rr', 0):7.1f} мс")
                print(f"  SDNN:           {metrics.get('sdnn', 0):7.1f} мс")
                print(f"  RMSSD:          {metrics.get('rmssd', 0):7.1f} мс")
                
                if 'pnn50' in metrics:
                    print(f"  pNN50:          {metrics['pnn50']:7.2f} %")
                
                # TP (суммарная мощность)
                tp = metrics.get('sdnn', 0) ** 2
                print(f"  TP (SDNN²):     {tp:7.0f} мс²")
                
                # Спектральные мощности (если доступны)
                if all(k in metrics for k in ('vlf', 'lf', 'hf')):
                    print(f"\n  Спектральные мощности:")
                    print(f"    VLF (0.003-0.04 Гц): {metrics['vlf']:6.0f} мс²")
                    print(f"    LF  (0.04-0.15 Гц):  {metrics['lf']:6.0f} мс²")
                    print(f"    HF  (0.15-0.4 Гц):   {metrics['hf']:6.0f} мс²")
                    if metrics['hf'] > 0:
                        print(f"    LF/HF ratio:         {metrics['lf']/metrics['hf']:6.2f}")
                
                # === ИНДЕКС СТРЕССА ===
                if stress and 'si' in stress:
                    print(f"\n{'─'*50}")
                    print("  Индекс стресса (Баевского)")
                    print(f"{'─'*50}")
                    
                    si = stress['si']
                    try:
                        level = stress_level(si)
                    except Exception:
                        if si < 50:
                            level = 'низкий'
                        elif si < 100:
                            level = 'умеренный'
                        elif si < 200:
                            level = 'высокий'
                        else:
                            level = 'перенапряжение'
                    
                    icons = {
                        'низкий': '🟢',
                        'умеренный': '🟡',
                        'высокий': '🟠',
                        'перенапряжение': '🔴',
                    }
                    
                    print(f"  ИС:               {si:7.1f} усл.ед.")
                    
                    if 'amo' in stress:
                        print(f"  AMo (мода):       {stress['amo']:7.1f} %")
                    if 'mo' in stress:
                        print(f"  Mo (мода):        {stress['mo']:7.1f} мс")
                    if 'mxmn' in stress:
                        print(f"  MxDMn (размах):   {stress['mxmn']:7.1f} мс")
                    
                    print(f"  Уровень:          {icons.get(level, '⚪')} {level.upper()}")
                    
                    # Интерпретация
                    print(f"\n  Интерпретация:")
                    if si < 50:
                        print("    ✅ Отличная адаптация, высокий резерв")
                    elif si < 100:
                        print("    ✅ Норма, адекватная нагрузка")
                    elif si < 200:
                        print("    ⚠️  Напряжение регуляторных систем")
                    elif si < 500:
                        print("    ⚠️  Выраженное напряжение")
                    else:
                        print("    ❌ Критическое перенапряжение!")
                else:
                    print(f"\n  ⚠️  ИС не рассчитан")
                
                print(f"\n  Статус записи:    {metrics.get('status', 'unknown')}")
            else:
                print("\n  ⚠️  Недостаточно RR-интервалов для полного анализа")

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
        print(f"⚠️  Модуль не найден: {e}")
    except Exception as e:
        print(f"⚠️  Ошибка анализа: {e}")
        import traceback
        traceback.print_exc()