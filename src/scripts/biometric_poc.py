import os
import sys
import yaml
import numpy as np
from scipy.signal import find_peaks
from scipy import signal
from scipy.fft import fft, fftfreq
from dtaidistance import dtw

# ==============================================================================
# ИМПОРТ ВАШИХ МОДУЛЕЙ
# ==============================================================================
try:
    from ecg_generator import create_record, _default_profile
    from analysis import parse_ecg
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что ecg_generator.py и analysis.py находятся в той же папке.")
    sys.exit(1)

# ==============================================================================
# КОНФИГУРАЦИЯ РОДСТВЕННИКОВ
# ==============================================================================
RELATIVE_PAIRS = [
    ("filipp", "trofim"),  # Родственники
]

def are_relatives(name1, name2):
    """Проверяет, являются ли два имени родственниками."""
    name1_lower = name1.lower()
    name2_lower = name2.lower()
    for pair in RELATIVE_PAIRS:
        if (pair[0] in name1_lower and pair[1] in name2_lower) or \
           (pair[1] in name1_lower and pair[0] in name2_lower):
            return True
    return False

# ==============================================================================
# 1. ЗАГРУЗКА ПРОФИЛЕЙ И ДАННЫХ
# ==============================================================================
def load_and_mutate_profiles(yaml_path="ecg_profiles.yaml"):
    """Загружает реальный профиль и создает 4 КАРДИНАЛЬНО разные морфологии."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    base_profile = config['profiles']['real_c8208e2e'].copy()
    profiles = {}
    
    profiles["Person_A_Base"] = base_profile.copy()
    
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
    """Загружает реальные файлы из структурированных папок."""
    dataset = {}
    for person_name in os.listdir(base_dir):
        person_dir = os.path.join(base_dir, person_name)
        if os.path.isdir(person_dir):
            files = [os.path.join(person_dir, f) for f in os.listdir(person_dir) if f.endswith('.teamloggerh10')]
            if files:
                dataset[person_name] = sorted(files)
    return dataset

def parse_ecg_for_biometrics(raw_data, fs=None):
    """Парсинг ЭКГ БЕЗ медианного фильтра (для биометрии)."""
    if fs is None:
        fs = 130.0
    
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
    
    sig = np.asarray(samples, dtype=float)
    nyq = 0.5 * fs
    
    if 0 < 50.0 < nyq:
        b_notch, a_notch = signal.iirnotch(50.0 / nyq, Q=30.0)
        sig = signal.filtfilt(b_notch, a_notch, sig)
    
    if 0 < 0.5 < 50.0 < nyq:
        b_band, a_band = signal.butter(4, [0.5 / nyq, 50.0 / nyq], btype='band')
        sig = signal.filtfilt(b_band, a_band, sig)
    
    return sig

# ==============================================================================
# 2. ИЗВЛЕЧЕНИЕ ПРИЗНАКОВ (ФОРМА + СПЕКТР)
# ==============================================================================
def extract_features_from_file(filepath, fs=130, use_qrs_only=True):
    """
    Извлекает КОМБИНИРОВАННЫЕ признаки:
    1. Форма QRS (временная область)
    2. Спектральные характеристики (частотная область)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        raw_data = f.read()
    
    ecg_clean = parse_ecg_for_biometrics(raw_data, fs=fs)
    
    min_r_height = np.mean(ecg_clean) + 1.5 * np.std(ecg_clean)
    rough_peaks, _ = find_peaks(ecg_clean, distance=int(0.3 * fs), height=min_r_height)
    
    # QRS-окно: 200 мс
    if use_qrs_only:
        window_samples = int(0.2 * fs)
    else:
        window_samples = int(0.6 * fs)
    
    half_win = window_samples // 2
    
    shape_cycles = []
    spectral_features = []
    
    for rough_peak in rough_peaks:
        if rough_peak - half_win > 0 and rough_peak + half_win < len(ecg_clean):
            cycle = ecg_clean[rough_peak - half_win : rough_peak + half_win].copy()
            
            # Выравнивание по R
            center = half_win
            search_range = 10
            local_region = cycle[max(0, center-search_range) : min(len(cycle), center+search_range)]
            r_offset = np.argmax(local_region) - min(center, search_range)
            if r_offset != 0:
                cycle = np.roll(cycle, -r_offset)
            
            # R-нормализация
            r_value = cycle[center]
            baseline = np.min(cycle[:max(1, int(0.05 * fs))])
            
            if abs(r_value - baseline) > 1e-8:
                r_normalized = (cycle - baseline) / (r_value - baseline)
                shape_cycles.append(r_normalized)
                
                # ⚡ СПЕКТРАЛЬНЫЕ ПРИЗНАКИ
                # FFT QRS-комплекса
                n = len(cycle)
                yf = fft(cycle)
                xf = fftfreq(n, 1/fs)
                
                # Берем только положительную половину спектра
                pos_mask = xf > 0
                xf_pos = xf[pos_mask]
                yf_pos = np.abs(yf[pos_mask])
                
                # Нормализуем спектр (максимум = 1)
                if np.max(yf_pos) > 1e-8:
                    yf_pos = yf_pos / np.max(yf_pos)
                
                # Извлекаем ключевые спектральные характеристики:
                # 1. Доминирующая частота
                # 2. Ширина спектра на половине высоты
                # 3. Энергия в разных диапазонах
                
                # Доминирующая частота (кроме DC компоненты)
                if len(yf_pos) > 1:
                    dom_freq_idx = np.argmax(yf_pos[1:]) + 1
                    dom_freq = xf_pos[dom_freq_idx]
                else:
                    dom_freq = 0
                
                # Энергия в диапазонах (аналогично HRV, но для QRS)
                # QRS основная энергия: 10-40 Гц
                low_freq_mask = (xf_pos >= 5) & (xf_pos < 15)
                mid_freq_mask = (xf_pos >= 15) & (xf_pos < 30)
                high_freq_mask = (xf_pos >= 30) & (xf_pos < 50)
                
                energy_low = np.trapezoid(yf_pos[low_freq_mask], xf_pos[low_freq_mask]) if np.any(low_freq_mask) else 0
                energy_mid = np.trapezoid(yf_pos[mid_freq_mask], xf_pos[mid_freq_mask]) if np.any(mid_freq_mask) else 0
                energy_high = np.trapezoid(yf_pos[high_freq_mask], xf_pos[high_freq_mask]) if np.any(high_freq_mask) else 0

                total_energy = energy_low + energy_mid + energy_high
                if total_energy > 1e-8:
                    energy_low /= total_energy
                    energy_mid /= total_energy
                    energy_high /= total_energy
                
                # Сохраняем спектральные признаки
                spectral_features.append([
                    dom_freq / 50.0,        # Нормализованная доминирующая частота
                    energy_low,              # Доля низкой частоты
                    energy_mid,              # Доля средней частоты
                    energy_high,             # Доля высокой частоты
                ])
                
    if len(shape_cycles) < 3 or len(spectral_features) < 3:
        return None, None
    
    # Усредняем признаки через медиану
    shape_template = np.median(shape_cycles, axis=0)
    spectral_template = np.median(spectral_features, axis=0)
    
    return shape_template, spectral_template

# ==============================================================================
# 3. КОМБИНИРОВАННОЕ РАССТОЯНИЕ
# ==============================================================================
def compute_combined_distance(query_shape, query_spectrum, ref_shape, ref_spectrum, 
                              shape_weight=0.6, spectrum_weight=0.4):
    """
    Вычисляет взвешенное расстояние между двумя наборами признаков.
    shape_weight + spectrum_weight должны давать 1.0
    """
    # Расстояние по форме (DTW)
    shape_dist = dtw.distance_fast(query_shape.astype(np.double), ref_shape.astype(np.double))
    
    # Расстояние по спектру (евклидово)
    spectrum_dist = np.sqrt(np.sum((query_spectrum - ref_spectrum) ** 2))
    
    # Нормализуем расстояния (эмпирически)
    # DTW обычно дает значения 0.1-2.0, спектральное 0.01-0.5
    norm_shape_dist = shape_dist / 2.0
    norm_spectrum_dist = spectrum_dist / 0.5
    
    # Комбинированное расстояние
    combined_dist = (shape_weight * norm_shape_dist + 
                     spectrum_weight * norm_spectrum_dist)
    
    return combined_dist, shape_dist, spectrum_dist

# ==============================================================================
# 4. ИДЕНТИФИКАЦИЯ
# ==============================================================================
def identify_person(query_filepath, ref_data, ref_labels, fs=130, threshold=0.35):
    """
    Сравнивает query-файл с эталонами. 
    Если лучшее расстояние > threshold, возвращает "UNKNOWN".
    """
    query_shape, query_spectrum = extract_features_from_file(query_filepath, fs)
    if query_shape is None or query_spectrum is None:
        return "UNKNOWN", 9999, [], None, None
    
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
            
    # ⚡ ГЛАВНОЕ ИЗМЕНЕНИЕ: Порог отсечения
    if min_dist > threshold:
        return "UNKNOWN", min_dist, distances, query_shape, query_spectrum
        
    return best_match, min_dist, distances, query_shape, query_spectrum

# ==============================================================================
# 5. ВИЗУАЛИЗАЦИЯ
# ==============================================================================
import matplotlib.pyplot as plt

def debug_plot_features(filepath, output_png="debug_features.png"):
    """Сохраняет график формы и спектра для визуальной проверки."""
    shape, spectrum = extract_features_from_file(filepath, fs=130)
    if shape is None:
        print(f"    ⚠️  Не удалось извлечь признаки из {filepath}")
        return
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # Форма QRS
    ax1.plot(shape, linewidth=1.5)
    ax1.set_title(f"QRS Shape\n{os.path.basename(filepath)[:40]}")
    ax1.axhline(0, color='black', linewidth=1, linestyle='--')
    ax1.axhline(1, color='red', linewidth=1, linestyle='--')
    ax1.set_xlabel("Samples")
    ax1.set_ylabel("Normalized Amplitude")
    ax1.grid(True, alpha=0.3)
    
    # Спектральные признаки
    labels = ['DomFreq', 'EnergyLow\n(5-15Hz)', 'EnergyMid\n(15-30Hz)', 'EnergyHigh\n(30-50Hz)']
    x_pos = np.arange(len(labels))
    ax2.bar(x_pos, spectrum, color=['blue', 'green', 'orange', 'red'])
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(labels, fontsize=8)
    ax2.set_ylabel("Normalized Value")
    ax2.set_title("Spectral Features")
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    plt.close()
    print(f"    📊 График сохранен: {output_png}")

def debug_compare_templates(ref_data, ref_labels, name1, name2, output_png="compare_templates.png"):
    """Сравнивает шаблоны двух конкретных людей."""
    idx1 = ref_labels.index(name1) if name1 in ref_labels else None
    idx2 = ref_labels.index(name2) if name2 in ref_labels else None
    
    if idx1 is None or idx2 is None:
        return
        
    shape1, spec1 = ref_data[idx1]
    shape2, spec2 = ref_data[idx2]
    
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
    print(f"\n📊 Сравнение шаблонов сохранено: {output_png}")

# ==============================================================================
# 6. ЗАПУСК И ОЦЕНКА С РАЗДЕЛЕНИЕМ СТАТИСТИКИ
# ==============================================================================
# ==============================================================================
# 6. ЗАПУСК И ОЦЕНКА С РАЗДЕЛЕНИЕМ СТАТИСТИКИ
# ==============================================================================
def run_poc():
    print("="*70)
    print(" 🚀 ЗАПУСК ПРОТОТИПА БИОМЕТРИИ ЭКГ (КОМБИНИРОВАННЫЕ ПРИЗНАКИ + ОТКАЗ)")
    print("="*70)
    
    dataset = load_real_dataset()
    
    if not dataset:
        print("❌ Не найдены данные в папке real_ecg_data")
        return
    
    print(f"\n📁 Найдено {len(dataset)} человек:")
    for name in sorted(dataset.keys()):
        n_files = len(dataset[name])
        rel_marker = " [REL]" if any(are_relatives(name, other) for other in dataset.keys() if other != name) else ""
        print(f"   • {name}: {n_files} записей{rel_marker}")
    
    # Создание усиленных эталонов
    print("\n️ Создание эталонных шаблонов (форма + спектр)...")
    ref_data = []
    ref_labels = []
    
    for person_name, files in dataset.items():
        shapes = []
        spectrums = []
        valid_files = 0
        
        # ⚡ ИСПОЛЬЗУЕМ БОЛЬШЕ ЗАПИСЕЙ (до 7 вместо 3)
        for i in range(min(7, len(files))):
            shape, spectrum = extract_features_from_file(files[i])
            if shape is not None and spectrum is not None:
                shapes.append(shape)
                spectrums.append(spectrum)
                valid_files += 1
        
        if len(shapes) >= 3:  # Нужно минимум 3 качественных записи
            # ⚡ ИСПОЛЬЗУЕМ МЕДИАНУ ВМЕСТО СРЕДНЕГО для подавления выбросов
            robust_shape = np.median(shapes, axis=0)
            robust_spectrum = np.median(spectrums, axis=0)
            ref_data.append((robust_shape, robust_spectrum))
            ref_labels.append(person_name)
            print(f"   ✅ {person_name}: шаблон создан ({valid_files} записей, медиана)")
        else:
            print(f"   ⚠️  {person_name}: НЕ ХВАТАЕТ КАЧЕСТВЕННЫХ ДАННЫХ (нужно ≥3, есть {valid_files})")
    
    # Тестирование с разделением статистики
    print("\n🔍 Тестирование идентификации (порог отсева = 0.35)...")
    
    total_correct = 0
    total_tests = 0
    unknown_count = 0
    
    relative_correct = 0
    relative_tests = 0
    
    non_relative_correct = 0
    non_relative_tests = 0
    
    detailed_results = []
    
    for person_name, files in dataset.items():
        for i in range(1, len(files)):
            query_file = files[i]
            pred_name, min_dist, all_dists, _, _ = identify_person(query_file, ref_data, ref_labels)
            
            total_tests += 1
            is_correct = (pred_name == person_name)
            is_unknown = (pred_name == "UNKNOWN")
            
            # Определяем, родственная ли это пара
            is_relative_pair = any(are_relatives(person_name, ref_label) for ref_label, _, _, _ in all_dists)
            
            if is_unknown:
                unknown_count += 1
            else:
                if is_relative_pair:
                    relative_tests += 1
                    if is_correct:
                        relative_correct += 1
                else:
                    non_relative_tests += 1
                    if is_correct:
                        non_relative_correct += 1
                
                if is_correct:
                    total_correct += 1
            
            # Форматируем вывод
            dists_str = ", ".join([
                f"{lbl.split('_')[0]}: {d:.2f}" 
                for lbl, d, _, _ in sorted(all_dists, key=lambda x: x[1])[:3]
            ])
            
            if is_unknown:
                status = "⚠️"
                pred_str = "UNKNOWN"
            else:
                status = "✅" if is_correct else "❌"
                pred_str = pred_name.split('_')[0]
                
            rel_marker = "👥" if is_relative_pair else "  "
            print(f"{status} {rel_marker} {person_name}#{i+1:2d} -> {pred_str:10s} (dist: {dists_str})")
            
            detailed_results.append({
                'person': person_name,
                'file_idx': i+1,
                'predicted': pred_name,
                'is_correct': is_correct,
                'is_unknown': is_unknown,
                'is_relative': is_relative_pair,
                'distance': min_dist
            })
    
    # Итоговая статистика
    print("\n" + "="*70)
    print("📊 СТАТИСТИКА ПО ГРУППАМ (с учетом порога отсева):")
    print("="*70)
    
    if total_tests > 0:
        accepted_tests = total_tests - unknown_count
        if accepted_tests > 0:
            accepted_acc = (total_correct / accepted_tests) * 100
            print(f"\n🎯 ТОЧНОСТЬ (среди принятых): {total_correct}/{accepted_tests} ({accepted_acc:.1f}%)")
        print(f"⚠️  Отказов (UNKNOWN): {unknown_count}/{total_tests} ({(unknown_count/total_tests)*100:.1f}%)")
    
    if non_relative_tests > 0:
        non_rel_unknowns = sum(1 for r in detailed_results if r['is_unknown'] and not r['is_relative'])
        non_rel_accepted = non_relative_tests - non_rel_unknowns
        if non_rel_accepted > 0:
            non_rel_acc = (non_relative_correct / non_rel_accepted) * 100
            print(f"✅ Неродственные (точность):   {non_relative_correct}/{non_rel_accepted} ({non_rel_acc:.1f}%)")
    
    if relative_tests > 0:
        rel_unknowns = sum(1 for r in detailed_results if r['is_unknown'] and r['is_relative'])
        rel_accepted = relative_tests - rel_unknowns
        if rel_accepted > 0:
            rel_acc = (relative_correct / rel_accepted) * 100
            print(f"👥 Родственники (точность):     {relative_correct}/{rel_accepted} ({rel_acc:.1f}%)")
    
    print("\n" + "="*70)
    
    # Анализ результатов
    if 'non_rel_acc' in locals() and 'rel_acc' in locals():
        if non_rel_acc > 65 and rel_acc < 50:
            print("💡 ВЫВОД: Система надежно различает неродственных людей,")
            print("   но для близких родственников требуется дополнительный фактор.")
        elif non_rel_acc > 75:
            print("✅ ОТЛИЧНЫЙ РЕЗУЛЬТАТ для одноотводной ЭКГ!")
        else:
            print("💡 ВЫВОД: Требуется дополнительная очистка данных или расширение эталонной базы.")
    
    print("="*70)
    
    # ⚡ ВИЗУАЛЬНАЯ ОТЛАДКА: Сравниваем шаблоны проблемных пар
    print("\n🔍 Генерация сравнительных графиков шаблонов...")
    debug_compare_templates(ref_data, ref_labels, 'konstantin', 'andrey', "compare_konstantin_andrey.png")
    debug_compare_templates(ref_data, ref_labels, 'filipp', 'trofim', "compare_filipp_trofim.png")
    print("✅ Готово! Проверьте файлы compare_*.png в папке скрипта.")

if __name__ == "__main__":
    run_poc()