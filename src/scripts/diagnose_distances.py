"""
diagnose_distances.py — диагностика распределения расстояний между записями и шаблонами.
Исправлена версия с защитой от inf/nan и фильтрацией выбросов для графиков.
"""
import os
import sys
import json
import numpy as np
from dtaidistance import dtw
import matplotlib.pyplot as plt

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))

try:
    from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete
except ImportError:
    print("❌ Ошибка: Не удалось импортировать 'models'.")
    sys.exit(1)

from scipy.signal import find_peaks, iirnotch, butter, filtfilt
from scipy.fft import fft, fftfreq

FS = 130.0
MAX_PENALTY = 10.0  # Защита от inf/nan, как в основном скрипте

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

def main():
    db_path = "../data/ecg.db"
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        sys.exit(1)

    print("🔍 Загрузка данных...")
    session = get_session(db_path)
    
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

    print(f"   Шаблонов: {len(templates)}")

    records_data = []
    all_raw = session.query(ECGRecord.athlete_id, ECGRaw.raw_data).join(ECGRaw, ECGRecord.id == ECGRaw.record_id).all()
    
    for ath_id, raw_data in all_raw:
        if ath_id not in templates:
            continue
        
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

    print(f"   Записей: {len(records_data)}")

    own_distances = []
    other_distances = []
    inf_count_own = 0
    inf_count_other = 0
    
    print("\n📏 Расчет расстояний...")
    for i, rec in enumerate(records_data):
        if i % 100 == 0:
            print(f"   Обработано: {i}/{len(records_data)}")
        
        for tpl_ath_id, tpl_data in templates.items():
            try:
                s_dist = dtw.distance_fast(rec['shape'].astype(np.double), tpl_data['shape'].astype(np.double))
                sp_dist = np.sqrt(np.sum((rec['spec'] - tpl_data['spec']) ** 2))
                
                combined_dist = 0.6 * (s_dist / 2.0) + 0.4 * (sp_dist / 0.5)
                
                # 🛡️ ЗАЩИТА ОТ inf/nan
                if not np.isfinite(combined_dist) or combined_dist > 5.0:
                    if rec['athlete_id'] == tpl_ath_id:
                        inf_count_own += 1
                    else:
                        inf_count_other += 1
                    continue # Пропускаем битые расчеты для чистой статистики
                
                if rec['athlete_id'] == tpl_ath_id:
                    own_distances.append(combined_dist)
                else:
                    other_distances.append(combined_dist)
            except Exception:
                if rec['athlete_id'] == tpl_ath_id:
                    inf_count_own += 1
                else:
                    inf_count_other += 1

    print(f"\n📊 Статистика расстояний (ТОЛЬКО ВАЛИДНЫЕ ДАННЫЕ):")
    print(f"   Свои пары: {len(own_distances)} (пропущено битых: {inf_count_own})")
    if own_distances:
        print(f"   Среднее: {np.mean(own_distances):.3f}")
        print(f"   Медиана: {np.median(own_distances):.3f}")
        print(f"   Мин: {np.min(own_distances):.3f}")
        print(f"   Макс: {np.max(own_distances):.3f}")
        print(f"   Std: {np.std(own_distances):.3f}")
    
    print(f"\n   Чужие пары: {len(other_distances)} (пропущено битых: {inf_count_other})")
    if other_distances:
        print(f"   Среднее: {np.mean(other_distances):.3f}")
        print(f"   Медиана: {np.median(other_distances):.3f}")
        print(f"   Мин: {np.min(other_distances):.3f}")
        print(f"   Макс: {np.max(other_distances):.3f}")
        print(f"   Std: {np.std(other_distances):.3f}")

    # Визуализация (ограничиваем диапазон до 1.0, чтобы увидеть основную массу данных)
    if own_distances and other_distances:
        plt.figure(figsize=(12, 6))
        plt.hist(own_distances, bins=50, alpha=0.6, label=f'Свои (n={len(own_distances)})', color='green', density=True)
        plt.hist(other_distances, bins=50, alpha=0.6, label=f'Чужие (n={len(other_distances)})', color='red', density=True)
        plt.xlabel('Расстояние')
        plt.ylabel('Плотность')
        plt.title('Распределение расстояний: свои vs чужие (без выбросов > 1.0)')
        plt.legend()
        plt.xlim(0, 1.0) # Фокус на значимых значениях
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig('distance_distribution.png', dpi=150)
        print(f"\n📈 График сохранен: distance_distribution.png")

    # Анализ перекрытия при разных порогах
    print(f"\n🔍 Анализ точности при разных порогах:")
    print(f"{'Порог':<8} | {'TPR (Свои верно)':<18} | {'TNR (Чужие верно)':<18} | {'Balanced Acc'}")
    print("-" * 65)
    
    best_thresh = 0.20
    best_score = 0.0
    
    for thresh in [0.10, 0.15, 0.20, 0.25, 0.30]:
        own_correct = sum(1 for d in own_distances if d <= thresh)
        other_correct = sum(1 for d in other_distances if d > thresh)
        
        tpr = own_correct / len(own_distances) if own_distances else 0
        tnr = other_correct / len(other_distances) if other_distances else 0
        balanced = (tpr + tnr) / 2
        
        if balanced > best_score:
            best_score = balanced
            best_thresh = thresh
            
        print(f"{thresh:<8.2f} | {tpr*100:<18.1f}% | {tnr*100:<18.1f}% | {balanced*100:.1f}%")

    print(f"\n💡 РЕКОМЕНДАЦИЯ:")
    print(f"   Оптимальный порог: {best_thresh}")
    print(f"   Ожидаемая сбалансированная точность: {best_score*100:.1f}%")
    if inf_count_own > len(own_distances) * 0.1:
        print(f"   ⚠️ ВНИМАНИЕ: {inf_count_own} записей ('своих') дают сбой расчета (inf).")
        print(f"   Это может быть причиной низкой точности. Проверьте качество этих записей.")

    session.close()

if __name__ == "__main__":
    main()