"""
optimize_biometrics.py — скрипт для поиска оптимальных параметров биометрической модели.
Использует Grid Search для максимизации точности распознавания на имеющихся данных в БД.
"""
import os
import sys
import json
import numpy as np
from dtaidistance import dtw
from itertools import product

# Добавляем путь к models
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))

try:
    from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete
except ImportError:
    print("❌ Ошибка: Не удалось импортировать 'models'. Убедитесь, что запускаете из папки scripts.")
    sys.exit(1)

# ==============================================================================
# ФУНКЦИИ ИЗВЛЕЧЕНИЯ ПРИЗНАКОВ (копия из ecg_biometrics.py для автономности)
# ==============================================================================
from scipy.signal import find_peaks, iirnotch, butter, filtfilt
from scipy.fft import fft, fftfreq

FS = 130.0

def _parse_and_clean_ecg(raw_data, fs=FS):
    lines = raw_data.split('\n')
    in_ecg, samples = False, []
    for line in lines:
        line = line.strip()
        if line == '[ECG]': in_ecg = True; continue
        if line.startswith('['): in_ecg = False; continue
        if in_ecg and ':' in line:
            try: 
                samples.extend(float(v) for v in line.split(':', 1)[1].split(',') if v.strip())
            except (ValueError, IndexError): pass
    
    sig = np.asarray(samples, dtype=float)
    if len(sig) < 20: return np.array([])
    
    nyq = 0.5 * fs
    try:
        if 0 < 50.0 < nyq:
            b, a = iirnotch(50.0 / nyq, Q=30.0)
            sig = filtfilt(b, a, sig)
        if 0 < 0.5 < 50.0 < nyq:
            b, a = butter(4, [0.5 / nyq, 50.0 / nyq], btype='band')
            sig = filtfilt(b, a, sig)
    except ValueError:
        return np.array([])
    return sig

def _extract_features(ecg_clean, fs=FS):
    min_r_height = np.mean(ecg_clean) + 1.5 * np.std(ecg_clean)
    rough_peaks, _ = find_peaks(ecg_clean, distance=int(0.3 * fs), height=min_r_height)
    half_win = int(0.1 * fs)
    shape_cycles, spectral_features = [], []
    
    for rough_peak in rough_peaks:
        if rough_peak - half_win > 0 and rough_peak + half_win < len(ecg_clean):
            cycle = ecg_clean[rough_peak - half_win : rough_peak + half_win].copy()
            center = half_win
            local_region = cycle[max(0, center-10) : min(len(cycle), center+10)]
            r_offset = np.argmax(local_region) - min(center, 10)
            if r_offset != 0: cycle = np.roll(cycle, -r_offset)
            
            r_value, baseline = cycle[center], np.min(cycle[:max(1, int(0.05 * fs))])
            if abs(r_value - baseline) > 1e-8:
                r_norm = (cycle - baseline) / (r_value - baseline)
                shape_cycles.append(r_norm)
                
                yf, xf = fft(cycle), fftfreq(len(cycle), 1/fs)
                xf_pos, yf_pos = xf[xf > 0], np.abs(yf[xf > 0])
                if np.max(yf_pos) > 1e-8: yf_pos /= np.max(yf_pos)
                
                dom_freq = xf_pos[np.argmax(yf_pos[1:]) + 1] if len(yf_pos) > 1 else 0
                masks = [(xf_pos >= 5) & (xf_pos < 15), (xf_pos >= 15) & (xf_pos < 30), (xf_pos >= 30) & (xf_pos < 50)]
                energies = [np.trapezoid(yf_pos[m], xf_pos[m]) if np.any(m) else 0 for m in masks]
                total = sum(energies)
                if total > 1e-8: energies = [e/total for e in energies]
                spectral_features.append([dom_freq / 50.0] + energies)

    if len(shape_cycles) < 3 or len(spectral_features) < 3: return None, None
    return np.median(shape_cycles, axis=0), np.median(spectral_features, axis=0)

# ==============================================================================
# ГЛАВНАЯ ЛОГИКА ОПТИМИЗАЦИИ
# ==============================================================================
def main():
    db_path = "../data/ecg.db" # Укажите правильный путь к вашей БД
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена по пути: {db_path}")
        sys.exit(1)

    print("🔍 Подключение к базе данных и загрузка шаблонов...")
    session = get_session(db_path)
    
    # 1. Загружаем все шаблоны
    templates_data = session.query(BiometricTemplate, Athlete).join(Athlete).all()
    templates = {}
    for tpl, athlete in templates_data:
        try:
            templates[athlete.id] = {
                'name': f"{athlete.last_name} {athlete.first_name}",
                'shape': np.array(json.loads(tpl.shape_template)),
                'spec': np.array(json.loads(tpl.spectrum_template))
            }
        except Exception:
            continue

    print(f"   ✅ Загружено шаблонов: {len(templates)}")

    # 2. Загружаем все записи и извлекаем признаки (КЭШИРОВАНИЕ)
    print("⚙️ Извлечение признаков из всех записей в БД (это может занять минуту)...")
    records_data = []
    all_raw = session.query(ECGRecord.athlete_id, ECGRaw.raw_data).join(ECGRaw, ECGRecord.id == ECGRaw.record_id).all()
    
    valid_count = 0
    for ath_id, raw_data in all_raw:
        if ath_id not in templates:
            continue # Пропускаем записи атлетов, у которых нет шаблона
        
        clean_ecg = _parse_and_clean_ecg(raw_data)
        if len(clean_ecg) == 0:
            continue
            
        shape, spec = _extract_features(clean_ecg)
        if shape is not None and spec is not None:
            records_data.append({
                'athlete_id': ath_id,
                'shape': shape,
                'spec': spec
            })
            valid_count += 1
            
    print(f"   ✅ Успешно обработано записей: {valid_count}")

    # 3. Предварительный расчет "сырых" расстояний (чтобы не считать DTW тысячи раз в цикле)
    print("📏 Предварительный расчет матрицы расстояний...")
    # Структура: precalculated_dists[record_index][template_athlete_id] = (shape_dist, spec_dist)
    precalculated_dists = []
    
    for rec in records_data:
        rec_dists = {}
        for tpl_ath_id, tpl_data in templates.items():
            try:
                s_dist = dtw.distance_fast(rec['shape'].astype(np.double), tpl_data['shape'].astype(np.double))
                sp_dist = np.sqrt(np.sum((rec['spec'] - tpl_data['spec']) ** 2))
                rec_dists[tpl_ath_id] = (s_dist, sp_dist)
            except Exception:
                rec_dists[tpl_ath_id] = (10.0, 10.0) # Штраф за ошибку
        precalculated_dists.append((rec['athlete_id'], rec_dists))

    # 4. GRID SEARCH: Перебор параметров
    print("\n🚀 Запуск Grid Search по параметрам...")
    thresholds = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    w_shapes = [0.5, 0.6, 0.7, 0.8] # w_spec будет 1.0 - w_shape
    
    results = []

    for thresh, w_s in product(thresholds, w_shapes):
        w_sp = 1.0 - w_s
        
        tp = 0 # True Positive (свой распознан как свой)
        fn = 0 # False Negative (свой распознан как чужой)
        tn = 0 # True Negative (чужой распознан как чужой)
        fp = 0 # False Positive (чужой распознан как свой)

        for true_ath_id, rec_dists in precalculated_dists:
            best_match_id = None
            min_combined_dist = float('inf')
            
            # Находим лучшее совпадение для этой записи при текущих весах
            for tpl_ath_id, (s_dist, sp_dist) in rec_dists.items():
                combined_dist = w_s * (s_dist / 2.0) + w_sp * (sp_dist / 0.5)
                if combined_dist < min_combined_dist:
                    min_combined_dist = combined_dist
                    best_match_id = tpl_ath_id

            # Оцениваем результат
            if best_match_id == true_ath_id:
                if min_combined_dist <= thresh:
                    tp += 1 # Верно: свой и расстояние в пороге
                else:
                    fn += 1 # Ошибка: свой, но расстояние слишком большое (ложный отказ)
            else:
                if min_combined_dist <= thresh:
                    fp += 1 # Ошибка: чужой, но расстояние маленькое (ложное срабатывание)
                else:
                    tn += 1 # Верно: чужой и расстояние большое

        total_checks = tp + fn + tn + fp
        accuracy = (tp + tn) / total_checks if total_checks > 0 else 0
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0 # Чувствительность
        tnr = tn / (tn + fp) if (tn + fp) > 0 else 0 # Специфичность
        
        # Сбалансированная точность (хорошо работает при дисбалансе классов)
        balanced_acc = (tpr + tnr) / 2.0

        results.append({
            'threshold': thresh,
            'w_shape': w_s,
            'w_spec': round(w_sp, 1),
            'accuracy': accuracy,
            'tpr': tpr,
            'tnr': tnr,
            'balanced_acc': balanced_acc,
            'tp': tp, 'fn': fn, 'tn': tn, 'fp': fp
        })

    # 5. Сортировка результатов по сбалансированной точности
    results.sort(key=lambda x: x['balanced_acc'], reverse=True)

    print("\n" + "="*80)
    print("🏆 ТОП-5 ЛУЧШИХ НАБОРОВ ПАРАМЕТРОВ")
    print("="*80)
    print(f"{'Порог':<8} | {'Вес Shape':<10} | {'Вес Spec':<10} | {'Balanced Acc':<14} | {'TPR (Свои)':<12} | {'TNR (Чужие)':<12}")
    print("-" * 80)
    
    for i, res in enumerate(results[:5]):
        print(f"{res['threshold']:<8.2f} | {res['w_shape']:<10.1f} | {res['w_spec']:<10.1f} | "
              f"{res['balanced_acc']*100:<14.2f}% | {res['tpr']*100:<12.2f}% | {res['tnr']*100:<12.2f}%")
        
    print("="*80)
    
    # Рекомендация
    best = results[0]
    print(f"\n💡 РЕКОМЕНДАЦИЯ:")
    print(f"   Установите в ecg_biometrics.py:")
    print(f"   BIOMETRIC_THRESHOLD = {best['threshold']}")
    print(f"   В формуле расстояния используйте вес shape = {best['w_shape']}, spec = {best['w_spec']}")
    print(f"   (Ожидаемая точность распознавания: ~{best['balanced_acc']*100:.1f}%)")

    session.close()

if __name__ == "__main__":
    main()