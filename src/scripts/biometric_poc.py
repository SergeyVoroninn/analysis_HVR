"""
biometric_poc.py — автономный PoC скрипт для оценки биометрической модели на реальных данных.
Теперь полностью синхронизирован с основным приложением через импорт из ecg_biometrics.
"""
import os
import sys
import yaml
import numpy as np
from dtaidistance import dtw
import matplotlib.pyplot as plt

# ==============================================================================
# ИМПОРТ ИЗ ОСНОВНОГО ПРИЛОЖЕНИЯ (Устранение дублирования и хардкода)
# ==============================================================================
try:
    from ecg_generator import create_record, _default_profile
    from analysis import parse_ecg
    # Импортируем готовые функции и конфиг! Больше никаких копий кода.
    from ecg_biometrics import _parse_and_clean_ecg, _extract_features, cfg
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что запускаете скрипт из папки scripts или настроили PYTHONPATH.")
    sys.exit(1)

# ==============================================================================
# КОНФИГУРАЦИЯ РОДСТВЕННИКОВ (Бизнес-логика, оставлена как есть)
# ==============================================================================
from app_constants import HARDCODED_RELATIVE_PAIRS as RELATIVE_PAIRS

def are_relatives(name1, name2):
    name1_lower, name2_lower = name1.lower(), name2.lower()
    for pair in RELATIVE_PAIRS:
        if (pair[0] in name1_lower and pair[1] in name2_lower) or \
           (pair[1] in name1_lower and pair[0] in name2_lower):
            return True
    return False

# ==============================================================================
# 1. ЗАГРУЗКА ДАННЫХ
# ==============================================================================
def load_and_mutate_profiles(yaml_path="ecg_profiles.yaml"):
    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    base_profile = config['profiles']['real_c8208e2e'].copy()
    profiles = {"Person_A_Base": base_profile.copy()}
    
    p_b = base_profile.copy()
    p_b['s_wave'] = p_b['s_wave'].copy()
    p_b['s_wave']['amplitude'] = -4000
    profiles["Person_B_Deep_S"] = p_b
    
    p_c = base_profile.copy()
    p_c['t_wave'] = p_c['t_wave'].copy()
    p_c['t_wave']['amplitude'] = 1800
    profiles["Person_C_Tall_T"] = p_c
    
    p_d = base_profile.copy()
    p_d['t_wave'] = p_d['t_wave'].copy()
    p_d['t_wave']['amplitude'] = -1200
    profiles["Person_D_Inverted_T"] = p_d
    
    return profiles

def load_real_dataset(base_dir="real_ecg_data"):
    dataset = {}
    if not os.path.exists(base_dir):
        return dataset
    for person_name in os.listdir(base_dir):
        person_dir = os.path.join(base_dir, person_name)
        if os.path.isdir(person_dir):
            files = [os.path.join(person_dir, f) for f in os.listdir(person_dir) if f.endswith('.teamloggerh10')]
            if files:
                dataset[person_name] = sorted(files)
    return dataset

# ==============================================================================
# 2. КОМБИНИРОВАННОЕ РАССТОЯНИЕ (Использует cfg вместо хардкода)
# ==============================================================================
def compute_combined_distance(query_shape, query_spectrum, ref_shape, ref_spectrum):
    shape_dist = dtw.distance_fast(query_shape.astype(np.double), ref_shape.astype(np.double))
    spectrum_dist = np.sqrt(np.sum((query_spectrum - ref_spectrum) ** 2))
    
    # ИСПОЛЬЗУЕМ КОНФИГ для нормализации и весов
    norm_shape_dist = shape_dist / cfg.SHAPE_NORM_FACTOR
    norm_spectrum_dist = spectrum_dist / cfg.SPEC_NORM_FACTOR
    
    combined_dist = (cfg.SHAPE_WEIGHT * norm_shape_dist + 
                     cfg.SPEC_WEIGHT * norm_spectrum_dist)
    
    return combined_dist, shape_dist, spectrum_dist

# ==============================================================================
# 3. ИДЕНТИФИКАЦИЯ
# ==============================================================================
def identify_person(query_filepath, ref_data, ref_labels, threshold=None):
    if threshold is None:
        threshold = cfg.BIOMETRIC_THRESHOLD
        
    # Используем импортированную функцию, она сама возьмет fs из cfg.FS
    query_shape, query_spectrum = _extract_features(_parse_and_clean_ecg(open(query_filepath, 'r', encoding='utf-8').read()))
    
    if query_shape is None or query_spectrum is None:
        return "UNKNOWN", BIOMETRIC_ERROR_DISTANCE, [], None, None
    
    best_match, min_dist = None, float('inf')
    distances = []
    
    for i, (ref_shape, ref_spectrum) in enumerate(ref_data):
        combined_dist, shape_dist, spectrum_dist = compute_combined_distance(
            query_shape, query_spectrum, ref_shape, ref_spectrum
        )
        distances.append((ref_labels[i], combined_dist, shape_dist, spectrum_dist))
        if combined_dist < min_dist:
            min_dist = combined_dist
            best_match = ref_labels[i]
            
    if min_dist > threshold:
        return "UNKNOWN", min_dist, distances, query_shape, query_spectrum
        
    return best_match, min_dist, distances, query_shape, query_spectrum

# ==============================================================================
# 4. ВИЗУАЛИЗАЦИЯ
# ==============================================================================
def debug_plot_features(filepath, output_png="debug_features.png"):
    shape, spectrum = _extract_features(_parse_and_clean_ecg(open(filepath, 'r', encoding='utf-8').read()))
    if shape is None:
        print(f"    ⚠️  Не удалось извлечь признаки из {filepath}")
        return
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.plot(shape, linewidth=1.5)
    ax1.set_title(f"QRS Shape\n{os.path.basename(filepath)[:40]}")
    ax1.axhline(0, color='black', linewidth=1, linestyle='--')
    ax1.axhline(1, color='red', linewidth=1, linestyle='--')
    ax1.grid(True, alpha=0.3)
    
    labels = ['DomFreq', 'EnergyLow\n(5-15Hz)', 'EnergyMid\n(15-30Hz)', 'EnergyHigh\n(30-50Hz)']
    ax2.bar(range(len(labels)), spectrum, color=['blue', 'green', 'orange', 'red'])
    ax2.set_xticks(range(len(labels)))
    ax2.set_xticklabels(labels, fontsize=8)
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    plt.close()

def debug_compare_templates(ref_data, ref_labels, name1, name2, output_png="compare_templates.png"):
    idx1 = ref_labels.index(name1) if name1 in ref_labels else None
    idx2 = ref_labels.index(name2) if name2 in ref_labels else None
    if idx1 is None or idx2 is None:
        return
        
    shape1, _ = ref_data[idx1]
    shape2, _ = ref_data[idx2]
    
    plt.figure(figsize=(10, 4))
    plt.plot(shape1, label=f'{name1} (Ref)', linewidth=2, alpha=0.8)
    plt.plot(shape2, label=f'{name2} (Ref)', linewidth=2, alpha=0.8, linestyle='--')
    plt.title(f"Сравнение QRS-шаблонов: {name1} vs {name2}")
    plt.axhline(0, color='black', linewidth=1, linestyle=':')
    plt.axhline(1, color='red', linewidth=1, linestyle=':')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(output_png, dpi=150)
    plt.close()

# ==============================================================================
# 5. ЗАПУСК И ОЦЕНКА
# ==============================================================================
def run_poc():
    print("="*70)
    print(" 🚀 ЗАПУСК ПРОТОТИПА БИОМЕТРИИ ЭКГ")
    print(f" ⚙️ Параметры из ECGConfig: FS={cfg.FS}, Порог={cfg.BIOMETRIC_THRESHOLD}")
    print("="*70)
    
    dataset = load_real_dataset()
    if not dataset:
        print("❌ Не найдены данные в папке real_ecg_data")
        return
    
    print(f"\n📁 Найдено {len(dataset)} человек:")
    for name in sorted(dataset.keys()):
        rel_marker = " [REL]" if any(are_relatives(name, other) for other in dataset.keys() if other != name) else ""
        print(f"   • {name}: {len(dataset[name])} записей{rel_marker}")
    
    print("\n️ Создание эталонных шаблонов (медиана)...")
    ref_data, ref_labels = [], []
    
    for person_name, files in dataset.items():
        shapes, spectrums = [], []
        for i in range(min(7, len(files))):
            shape, spectrum = _extract_features(_parse_and_clean_ecg(open(files[i], 'r', encoding='utf-8').read()))
            if shape is not None and spectrum is not None:
                shapes.append(shape)
                spectrums.append(spectrum)
        
        if len(shapes) >= 3:
            ref_data.append((np.median(shapes, axis=0), np.median(spectrums, axis=0)))
            ref_labels.append(person_name)
            print(f"   ✅ {person_name}: шаблон создан ({len(shapes)} записей)")
        else:
            print(f"   ⚠️  {person_name}: НЕ ХВАТАЕТ ДАННЫХ (нужно ≥3, есть {len(shapes)})")
    
    print(f"\n🔍 Тестирование идентификации (порог отсева = {cfg.BIOMETRIC_THRESHOLD})...")
    
    total_correct, total_tests, unknown_count = 0, 0, 0
    relative_correct, relative_tests, non_relative_correct, non_relative_tests = 0, 0, 0, 0
    detailed_results = []
    
    for person_name, files in dataset.items():
        for i in range(1, len(files)):
            query_file = files[i]
            pred_name, min_dist, all_dists, _, _ = identify_person(query_file, ref_data, ref_labels)
            
            total_tests += 1
            is_correct = (pred_name == person_name)
            is_unknown = (pred_name == "UNKNOWN")
            is_relative_pair = any(are_relatives(person_name, ref_label) for ref_label, _, _, _ in all_dists)
            
            if is_unknown:
                unknown_count += 1
            else:
                if is_relative_pair:
                    relative_tests += 1
                    if is_correct: relative_correct += 1
                else:
                    non_relative_tests += 1
                    if is_correct: non_relative_correct += 1
                
                if is_correct: total_correct += 1
            
            dists_str = ", ".join([f"{lbl.split('_')[0]}: {d:.2f}" for lbl, d, _, _ in sorted(all_dists, key=lambda x: x[1])[:3]])
            status = "⚠️" if is_unknown else ("✅" if is_correct else "❌")
            pred_str = "UNKNOWN" if is_unknown else pred_name.split('_')[0]
            rel_marker = "👥" if is_relative_pair else "  "
            
            print(f"{status} {rel_marker} {person_name}#{i+1:2d} -> {pred_str:10s} (dist: {dists_str})")
            detailed_results.append({'person': person_name, 'is_correct': is_correct, 'is_unknown': is_unknown, 'is_relative': is_relative_pair})
    
    print("\n" + "="*70)
    print("📊 СТАТИСТИКА:")
    print("="*70)
    if total_tests > 0:
        accepted_tests = total_tests - unknown_count
        if accepted_tests > 0:
            print(f"🎯 ТОЧНОСТЬ (среди принятых): {total_correct}/{accepted_tests} ({(total_correct/accepted_tests)*100:.1f}%)")
        print(f"⚠️  Отказов (UNKNOWN): {unknown_count}/{total_tests} ({(unknown_count/total_tests)*100:.1f}%)")
    
    if non_relative_tests > 0:
        non_rel_unknowns = sum(1 for r in detailed_results if r['is_unknown'] and not r['is_relative'])
        non_rel_accepted = non_relative_tests - non_rel_unknowns
        if non_rel_accepted > 0:
            print(f"✅ Неродственные (точность):   {non_relative_correct}/{non_rel_accepted} ({(non_relative_correct/non_rel_accepted)*100:.1f}%)")
    
    if relative_tests > 0:
        rel_unknowns = sum(1 for r in detailed_results if r['is_unknown'] and r['is_relative'])
        rel_accepted = relative_tests - rel_unknowns
        if rel_accepted > 0:
            print(f"👥 Родственники (точность):     {relative_correct}/{rel_accepted} ({(relative_correct/rel_accepted)*100:.1f}%)")
    
    print("="*70)
    print("🔍 Генерация сравнительных графиков шаблонов...")
    debug_compare_templates(ref_data, ref_labels, 'konstantin', 'andrey', "compare_konstantin_andrey.png")
    debug_compare_templates(ref_data, ref_labels, 'filipp', 'trofim', "compare_filipp_trofim.png")
    print("✅ Готово! Проверьте файлы compare_*.png.")

if __name__ == "__main__":
    run_poc()