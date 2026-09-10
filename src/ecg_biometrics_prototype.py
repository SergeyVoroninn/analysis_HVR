import numpy as np
from scipy import signal
from scipy.signal import find_peaks
from scipy.signal.windows import gaussian
from dtaidistance import dtw
import random

# ==============================================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Адаптировано из вашего кода)
# ==============================================================================

def clean_ecg_prototype(ecg_signal, fs, notch_freq=50.0, band_low=0.5, band_high=40.0):
    """Упрощенная версия вашей функции очистки для прототипа."""
    sig = np.asarray(ecg_signal, dtype=float).copy()
    nyq = 0.5 * fs
    
    # Notch фильтр (50 Гц)
    if 0 < notch_freq < nyq:
        b_notch, a_notch = signal.iirnotch(notch_freq / nyq, Q=30.0)
        sig = signal.filtfilt(b_notch, a_notch, sig)
    
    # Bandpass фильтр (0.5 - 40 Гц)
    if 0 < band_low < band_high < nyq:
        b_band, a_band = signal.butter(4, [band_low / nyq, band_high / nyq], btype='band')
        sig = signal.filtfilt(b_band, a_band, sig)
        
    return sig

def extract_normalized_cycles(ecg_clean, r_peaks, fs, window_ms=600):
    """
    Извлекает окна вокруг R-пиков и нормализует их по амплитуде (0..1).
    """
    window_samples = int(window_ms / 1000.0 * fs)
    half_win = window_samples // 2
    cycles = []
    
    for peak in r_peaks:
        # Проверяем границы, чтобы не выйти за массив
        if peak - half_win > 0 and peak + half_win < len(ecg_clean):
            cycle = ecg_clean[peak - half_win : peak + half_win]
            
            # Нормализация амплитуды (Min-Max scaling)
            min_val = np.min(cycle)
            max_val = np.max(cycle)
            if max_val - min_val > 1e-8: # Защита от деления на ноль (плоский шум)
                norm_cycle = (cycle - min_val) / (max_val - min_val)
                cycles.append(norm_cycle)
                
    return np.array(cycles)

def create_template(cycles):
    """
    Создает усредненный шаблон сердечного цикла из нескольких ударов.
    Использование медианы делает шаблон устойчивым к одиночным артефактам.
    """
    if len(cycles) == 0:
        return None
    return np.median(cycles, axis=0)

# ==============================================================================
# 2. ГЕНЕРАТОР ТЕСТОВЫХ ДАННЫХ (Замените это на загрузку ваших файлов)
# ==============================================================================

def generate_mock_dataset(num_people=4, records_per_person=8, fs=130):
    """Генерирует синтетические ЭКГ с РАЗЛИЧНОЙ морфологией для каждого человека."""
    dataset = {}
    
    # Уникальные "подписи" морфологии для каждого человека
    signatures = [
        {"s_wave": 0.0, "t_wave": 0.4},    # Person 1: Норма
        {"s_wave": -0.5, "t_wave": 0.3},   # Person 2: Глубокий зубец S
        {"s_wave": 0.1, "t_wave": 0.8},    # Person 3: Высокий зубец T
        {"s_wave": -0.2, "t_wave": -0.4}   # Person 4: Инвертированный (отрицательный) зубец T
    ]
    
    for person_id in range(1, num_people + 1):
        person_records = []
        sig = signatures[person_id - 1]
        
        for rec_idx in range(records_per_person):
            t = np.linspace(0, 10, 10 * fs)
            hr = random.uniform(60, 80)
            rr_interval_sec = 60.0 / hr
            
            # Генерируем времена пиков с небольшим варьированием (HRV)
            num_beats = int(10 / rr_interval_sec)
            peak_times = [0.5]
            for _ in range(num_beats):
                peak_times.append(peak_times[-1] + rr_interval_sec * random.uniform(0.9, 1.1))
            peak_times = np.array(peak_times[peak_times < 9.5])
            
            ecg = np.zeros_like(t)
            true_peaks_idx = []
            
            # Создаем уникальный шаблон удара для этого человека
            beat_len = int(fs * 0.6)  # 600 мс
            beat = np.zeros(beat_len)
            
            r_center = int(fs * 0.15)  # R-пик на 150 мс
            s_center = int(fs * 0.22)  # S-зубец на 220 мс
            t_center = int(fs * 0.35)  # T-зубец на 350 мс
            
            # R-всегда положительный
            r_wave = gaussian(int(fs * 0.08), std=int(fs * 0.02)) * 1.0
            r_start = max(0, r_center - len(r_wave)//2)
            r_end = min(beat_len, r_center + len(r_wave)//2)
            beat[r_start:r_end] += r_wave[:r_end-r_start]
            
            # S-зубец (уникален для человека)
            s_wave = gaussian(int(fs * 0.06), std=int(fs * 0.015)) * sig["s_wave"]
            s_start = max(0, s_center - len(s_wave)//2)
            s_end = min(beat_len, s_center + len(s_wave)//2)
            beat[s_start:s_end] += s_wave[:s_end-s_start]
            
            # T-зубец (уникален для человека)
            t_wave = gaussian(int(fs * 0.15), std=int(fs * 0.04)) * sig["t_wave"]
            t_start = max(0, t_center - len(t_wave)//2)
            t_end = min(beat_len, t_center + len(t_wave)//2)
            beat[t_start:t_end] += t_wave[:t_end-t_start]
            
            # Накладываем шаблоны на сигнал
            for p_time in peak_times:
                p_idx = int(p_time * fs)
                true_peaks_idx.append(p_idx)
                
                b_start = max(0, p_idx - r_center)
                b_end = min(len(t), b_start + beat_len)
                ecg[b_start:b_end] += beat[:b_end-b_start]
            
            # Добавляем шум и легкий дрейф изолинии (как в реальности)
            ecg += np.random.normal(0, 0.05, len(t))
            ecg += 0.1 * np.sin(2 * np.pi * 0.2 * np.linspace(0, 10, len(t)))
            
            person_records.append({
                "ecg": ecg,
                "true_peaks": true_peaks_idx,
                "fs": fs
            })
            
        dataset[f"Person_{person_id}"] = person_records
        
    return dataset

# ==============================================================================
# 3. ЯДРО ИДЕНТИФИКАЦИИ
# ==============================================================================

def identify_person(query_record, reference_templates, ref_labels, fs=130):
    """
    Сравнивает query_record со всеми reference_templates с помощью DTW.
    Возвращает метку человека с наименьшим расстоянием.
    """
    # 1. Очистка
    clean_ecg = clean_ecg_prototype(query_record["ecg"], fs)
    
    # 2. Поиск R-пиков (prominence подбирается под амплитуду)
    peaks, _ = find_peaks(clean_ecg, distance=int(0.3 * fs), prominence=np.ptp(clean_ecg)*0.4)
    
    # 3. Извлечение и создание шаблона
    cycles = extract_normalized_cycles(clean_ecg, peaks, fs, window_ms=600)
    query_template = create_template(cycles)
    
    if query_template is None:
        return "UNKNOWN (No peaks found)", 9999
    
    # 4. Сравнение с эталонами через DTW
    best_match = None
    min_distance = float('inf')
    distances = []
    
    for i, ref_template in enumerate(reference_templates):
        # dtw.distance_fast очень быстрый и эффективный
        dist = dtw.distance_fast(query_template.astype(np.double), ref_template.astype(np.double))
        distances.append((ref_labels[i], dist))
        
        if dist < min_distance:
            min_distance = dist
            best_match = ref_labels[i]
            
    return best_match, min_distance, distances

# ==============================================================================
# 4. ЗАПУСК И ОЦЕНКА (Leave-One-Out перекрестная проверка)
# ==============================================================================

def run_prototype():
    print("🔄 Генерация тестового набора данных (4 человека, по 8 записей)...")
    dataset = generate_mock_dataset(num_people=4, records_per_person=8, fs=130)
    
    print("⚙️ Создание эталонных шаблонов (берем первую запись каждого человека как референс)...")
    reference_templates = []
    ref_labels = []
    
    for person_id, records in dataset.items():
        # Для прототипа: эталоном будет средняя запись человека (индекс 0)
        ref_rec = records[0]
        clean_ecg = clean_ecg_prototype(ref_rec["ecg"], ref_rec["fs"])
        cycles = extract_normalized_cycles(clean_ecg, ref_rec["true_peaks"], ref_rec["fs"])
        template = create_template(cycles)
        
        reference_templates.append(template)
        ref_labels.append(person_id)
        print(f"   ✅ Шаблон для {person_id} создан (длина: {len(template)} семплов)")

    print("\n🔍 Начало тестирования идентификации (проверяем остальные записи)...")
    correct_predictions = 0
    total_tests = 0
    
    for person_id, records in dataset.items():
        # Тестируем на записях 1..7 (запись 0 мы использовали как референс)
        for i in range(1, len(records)):
            query_rec = records[i]
            
            predicted_id, min_dist, all_dists = identify_person(
                query_rec, reference_templates, ref_labels, fs=query_rec["fs"]
            )
            
            total_tests += 1
            is_correct = (predicted_id == person_id)
            if is_correct:
                correct_predictions += 1
                
            # Форматируем вывод расстояний для наглядности
            dists_str = ", ".join([f"{lbl}: {d:.2f}" for lbl, d in sorted(all_dists, key=lambda x: x[1])])
            
            status = "✅ ВЕРНО" if is_correct else "❌ ОШИБКА"
            print(f"[{status}] Запись {person_id}#{i+1} -> Предсказано: {predicted_id} (Расстояния: {dists_str})")

    accuracy = (correct_predictions / total_tests) * 100
    print("\n" + "="*60)
    print(f"🏆 ИТОГОВАЯ ТОЧНОСТЬ: {correct_predictions}/{total_tests} ({accuracy:.1f}%)")
    print("="*60)

if __name__ == "__main__":
    run_prototype()