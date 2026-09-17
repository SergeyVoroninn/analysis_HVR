"""
sort_unsorted.py — скрипт для кластеризации неизвестных ЭКГ-записей, 
поиска дубликатов и сопоставления с БД.

Важно: Исходная папка (unsorted) НЕ изменяется. Все файлы копируются в sorted.
Папка sorted полностью очищается перед каждым запуском.
"""
import os
import sys
import json
import shutil
import argparse
import hashlib
import numpy as np
from scipy.signal import find_peaks, iirnotch, butter, filtfilt
from scipy.fft import fft, fftfreq
from scipy.cluster.hierarchy import linkage, fcluster
from dtaidistance import dtw
from collections import Counter

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))

try:
    from models import get_session, BiometricTemplate, Athlete
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    print("⚠️ Предупреждение: Не удалось импортировать 'models'. Сопоставление с БД будет пропущено.")

FS = 130.0
BIOMETRIC_THRESHOLD = 0.20
MIN_GROUP_SIZE = 3
SUPPORTED_EXTENSIONS = ('.teamloggerh10', '.txt')
MAX_PENALTY_DISTANCE = 10.0

def get_file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def _parse_and_clean_ecg(raw_data, fs=FS):
    lines = raw_data.split('\n')
    in_ecg, samples = False, []
    for line in lines:
        line = line.strip()
        if line == '[ECG]':
            in_ecg = True
            continue
        if line.startswith('['):
            in_ecg = False
            continue
        if in_ecg and ':' in line:
            try:
                data_part = line.split(':', 1)[1]
                samples.extend(float(v) for v in data_part.split(',') if v.strip())
            except (ValueError, IndexError):
                pass

    sig = np.asarray(samples, dtype=float)
    if len(sig) < 20:
        return np.array([])

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
    window_samples, half_win = int(0.2 * fs), int(0.1 * fs)
    shape_cycles, spectral_features = [], []

    for rough_peak in rough_peaks:
        if rough_peak - half_win > 0 and rough_peak + half_win < len(ecg_clean):
            cycle = ecg_clean[rough_peak - half_win : rough_peak + half_win].copy()
            center = half_win
            local_region = cycle[max(0, center - 10) : min(len(cycle), center + 10)]
            r_offset = np.argmax(local_region) - min(center, 10)
            if r_offset != 0:
                cycle = np.roll(cycle, -r_offset)

            r_value, baseline = cycle[center], np.min(cycle[:max(1, int(0.05 * fs))])
            if abs(r_value - baseline) > 1e-8:
                r_norm = (cycle - baseline) / (r_value - baseline)
                shape_cycles.append(r_norm)

                yf, xf = fft(cycle), fftfreq(len(cycle), 1 / fs)
                xf_pos, yf_pos = xf[xf > 0], np.abs(yf[xf > 0])
                if np.max(yf_pos) > 1e-8:
                    yf_pos /= np.max(yf_pos)

                dom_freq = xf_pos[np.argmax(yf_pos[1:]) + 1] if len(yf_pos) > 1 else 0
                masks = [
                    (xf_pos >= 5) & (xf_pos < 15),
                    (xf_pos >= 15) & (xf_pos < 30),
                    (xf_pos >= 30) & (xf_pos < 50),
                ]
                energies = [np.trapezoid(yf_pos[m], xf_pos[m]) if np.any(m) else 0 for m in masks]
                total = sum(energies)
                if total > 1e-8:
                    energies = [e / total for e in energies]
                spectral_features.append([dom_freq / 50.0] + energies)

    if len(shape_cycles) < 3 or len(spectral_features) < 3:
        return None, None
    return np.median(shape_cycles, axis=0), np.median(spectral_features, axis=0)

def calculate_distance(data1, data2):
    try:
        shape_dist = dtw.distance_fast(data1['shape'].astype(np.double), data2['shape'].astype(np.double))
        spec_dist = np.sqrt(np.sum((data1['spec'] - data2['spec']) ** 2))
        dist = 0.6 * (shape_dist / 2.0) + 0.4 * (spec_dist / 0.5)
        if not np.isfinite(dist):
            return MAX_PENALTY_DISTANCE
        return float(dist)
    except Exception:
        return MAX_PENALTY_DISTANCE

def main():
    parser = argparse.ArgumentParser(description="Кластеризация и сопоставление ЭКГ с БД")
    parser.add_argument("source_folder", help="Имя исходной папки с файлами")
    parser.add_argument("--db", dest="db_path", help="Путь к файлу базы данных SQLite", default=None)
    args = parser.parse_args()

    source_dir = os.path.join(script_dir, args.source_folder)
    if not os.path.isdir(source_dir):
        print(f"❌ Ошибка: исходная папка '{source_dir}' не найдена.")
        sys.exit(1)

    target_dir = os.path.join(os.path.dirname(source_dir), "sorted")
    
    # 🛡️ ОЧИСТКА ТОЛЬКО ПАПКИ РЕЗУЛЬТАТОВ (sorted)
    if os.path.exists(target_dir):
        print(f" Очистка предыдущих результатов в: {target_dir}")
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    print(f"📁 Результаты будут сохранены в: {target_dir}")
    print(f" Исходная папка '{source_dir}' остается неизменной.\n")

    all_files = [f for f in os.listdir(source_dir) if f.lower().endswith(SUPPORTED_EXTENSIONS)]
    print(f"Найдено файлов для обработки: {len(all_files)}")

    print("Этап 0: Поиск точных дубликатов файлов...")
    hash_map = {}
    unique_files = []
    duplicate_files = []

    for filename in all_files:
        filepath = os.path.join(source_dir, filename)
        file_hash = get_file_hash(filepath)
        if file_hash in hash_map:
            duplicate_files.append(filepath)
        else:
            hash_map[file_hash] = filepath
            unique_files.append(filepath)

    print(f"  ✅ Найдено уникальных файлов: {len(unique_files)}")
    print(f"  🗑️ Найдено дубликатов: {len(duplicate_files)}")

    if duplicate_files:
        dup_dir = os.path.join(target_dir, "duplicates")
        os.makedirs(dup_dir, exist_ok=True)
        for dup_path in duplicate_files:
            # ✅ КОПИРУЕМ вместо перемещения
            shutil.copy2(dup_path, os.path.join(dup_dir, os.path.basename(dup_path)))
        print(f"  📂 Дубликаты скопированы в: {dup_dir}")

    all_files = [os.path.basename(f) for f in unique_files]
    undetermined_files = []
    valid_files_data = []

    print("Этап 1: Извлечение признаков из файлов...")
    for idx, filename in enumerate(all_files, 1):
        if idx % 100 == 0:
            print(f"  Обработано: {idx}/{len(all_files)}")
        
        filepath = os.path.join(source_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = f.read()
            clean_ecg = _parse_and_clean_ecg(raw)
            if len(clean_ecg) == 0:
                undetermined_files.append(filepath)
                continue

            shape, spec = _extract_features(clean_ecg)
            if shape is not None and spec is not None:
                valid_files_data.append({'filename': filename, 'filepath': filepath, 'shape': shape, 'spec': spec})
            else:
                undetermined_files.append(filepath)
        except Exception as e:
            print(f"  [!] Ошибка чтения {filename}: {e}")
            undetermined_files.append(filepath)

    print(f"Успешно обработано: {len(valid_files_data)}, Ошибки/неопределённые: {len(undetermined_files)}")

    if len(valid_files_data) < 2:
        print("Недостаточно файлов для кластеризации.")
        copy_to_undetermined(source_dir, target_dir, undetermined_files + [f['filepath'] for f in valid_files_data])
        generate_report(target_dir, {}, len(undetermined_files) + len(valid_files_data), len(duplicate_files))
        return

    print("Этап 2: Построение матрицы расстояний...")
    n = len(valid_files_data)
    condensed_dist_matrix = []
    for i in range(n):
        if i % 100 == 0:
            print(f"  Сравнение: {i}/{n}")
        for j in range(i + 1, n):
            dist = calculate_distance(valid_files_data[i], valid_files_data[j])
            condensed_dist_matrix.append(dist)

    # ==========================================================================
    # ЭТАП 3: Кластеризация
    # ==========================================================================
    print("Этап 3: Группировка файлов...")
    Z = linkage(condensed_dist_matrix, method='average')
    labels = fcluster(Z, t=BIOMETRIC_THRESHOLD, criterion='distance')
    cluster_sizes = Counter(labels)

    groups = {}
    for i, file_info in enumerate(valid_files_data):
        cid = labels[i]
        if cid not in groups:
            groups[cid] = []
        groups[cid].append(file_info)

    # ==========================================================================
    # ЭТАП 4: Копирование, Умное разделение и сопоставление с БД
    # ==========================================================================
    print("Этап 4: Копирование файлов и сопоставление с БД...")
    db_matches_report = {}
    
    if MODELS_AVAILABLE and args.db_path and os.path.exists(args.db_path):
        print(f"  🔍 Загрузка шаблонов из БД: {args.db_path}")
        session = get_session(args.db_path)
        db_templates = session.query(BiometricTemplate, Athlete).join(Athlete).all()
        print(f"  Найдено шаблонов в БД: {len(db_templates)}")
    else:
        db_templates = []
        if args.db_path:
            print(f"  ⚠️ База данных по пути '{args.db_path}' не найдена.")

    copied_count = 0
    small_group_files = []
    LARGE_GROUP_THRESHOLD = 50  # Если файлов в группе больше этого числа, пробуем разделить
    STRICT_THRESHOLD = 0.15     # Строгий порог для разделения родственников внутри большой группы

    # Создаем новый словарь для финальных групп (возможно, некоторые большие группы разделятся)
    final_groups = {}
    group_counter = 1000 # Начинаем новые ID с 1000, чтобы не конфликтовать с исходными

    for cid, group_files in groups.items():
        # 1. Отсекаем маленькие группы сразу
        if len(group_files) < MIN_GROUP_SIZE:
            small_group_files.extend(group_files)
            continue

        # 2. Умное разделение больших групп (попытка разделить родственников)
        if len(group_files) >= LARGE_GROUP_THRESHOLD and db_templates:
            print(f"  🔎 Группа {cid} большая ({len(group_files)} файлов). Пробую разделить на подгруппы...")
            
            # Строим матрицу расстояний ТОЛЬКО для этой группы
            n_sub = len(group_files)
            sub_dist_matrix = []
            for i in range(n_sub):
                for j in range(i + 1, n_sub):
                    dist = calculate_distance(group_files[i], group_files[j])
                    sub_dist_matrix.append(dist)
            
            # Кластеризуем с более строгим порогом
            Z_sub = linkage(sub_dist_matrix, method='average')
            sub_labels = fcluster(Z_sub, t=STRICT_THRESHOLD, criterion='distance')
            sub_cluster_sizes = Counter(sub_labels)
            
            # Если получилось разделить на 2 и более значимых подгруппы (каждая >= MIN_GROUP_SIZE)
            valid_sub_groups = [sub_id for sub_id, count in sub_cluster_sizes.items() if count >= MIN_GROUP_SIZE]
            
            if len(valid_sub_groups) >= 2:
                print(f"     ✅ Успешно разделена на {len(valid_sub_groups)} подгрупп!")
                for sub_id in valid_sub_groups:
                    new_cid = group_counter
                    group_counter += 1
                    final_groups[new_cid] = [group_files[i] for i in range(n_sub) if sub_labels[i] == sub_id]
                continue # Переходим к следующей исходной группе, эта уже разделена
            else:
                print(f"     ⚠️ Не удалось разделить строже. Оставляю как одну группу.")

        # 3. Если группа не была разделена, добавляем её как есть
        final_groups[cid] = group_files

    # Теперь обрабатываем final_groups (они уже отфильтрованы от мелких)
    for cid, group_files in final_groups.items():
        group_folder_name = f"group_{cid}"
        group_folder_path = os.path.join(target_dir, group_folder_name)
        os.makedirs(group_folder_path, exist_ok=True)

        for file_info in group_files:
            dest = os.path.join(group_folder_path, file_info['filename'])
            if not os.path.exists(dest):
                shutil.copy2(file_info['filepath'], dest)
                copied_count += 1

        # Сопоставление с БД для каждой (возможно, разделенной) группы
        best_match_name = "Неизвестно"
        min_dist = float('inf')
        
        if db_templates:
            group_shapes = np.array([f['shape'] for f in group_files])
            group_specs = np.array([f['spec'] for f in group_files])
            centroid_shape = np.median(group_shapes, axis=0)
            centroid_spec = np.median(group_specs, axis=0)
            centroid_data = {'shape': centroid_shape, 'spec': centroid_spec}

            for tpl, athlete in db_templates:
                try:
                    ref_shape = np.array(json.loads(tpl.shape_template))
                    ref_spec = np.array(json.loads(tpl.spectrum_template))
                    ref_data = {'shape': ref_shape, 'spec': ref_spec}
                    dist = calculate_distance(centroid_data, ref_data)
                    if dist < min_dist:
                        min_dist = dist
                        best_match_name = f"{athlete.last_name} {athlete.first_name} (ID: {athlete.id})"
                except Exception:
                    continue
        
        if min_dist > BIOMETRIC_THRESHOLD:
            best_match_name = f"Неизвестно (мин. расстояние: {min_dist:.3f} > порога {BIOMETRIC_THRESHOLD})"
        else:
            best_match_name = f"✅ {best_match_name} (расстояние: {min_dist:.3f})"

        db_matches_report[cid] = {'count': len(group_files), 'match': best_match_name}

    # Файлы из маленьких групп отправляем в undetermined
    if small_group_files:
        print(f"  ⚠️ Группы с < {MIN_GROUP_SIZE} файлами ({len(small_group_files)} файлов) отправлены в undetermined")
        for file_info in small_group_files:
            undetermined_files.append(file_info['filepath'])

    copy_to_undetermined(source_dir, target_dir, undetermined_files)
    generate_report(target_dir, db_matches_report, len(undetermined_files), len(duplicate_files))

    print("\n✅ Сортировка и анализ завершены!")
    print(f"   🗑️ Скопировано дубликатов: {len(duplicate_files)}")
    print(f"   📂 Скопировано в группы: {copied_count}")
    print(f"   ❓ Отправлено в undetermined: {len(undetermined_files)}")
    print(f"   🔒 Исходная папка не изменена.")


def copy_to_undetermined(source_dir, target_dir, filepaths):
    if not filepaths:
        return
    undetermined_dir = os.path.join(target_dir, "undetermined")
    os.makedirs(undetermined_dir, exist_ok=True)
    for filepath in filepaths:
        filename = os.path.basename(filepath)
        dest = os.path.join(undetermined_dir, filename)
        if os.path.exists(filepath) and not os.path.exists(dest):
            # ✅ КОПИРУЕМ вместо перемещения
            shutil.copy2(filepath, dest)

def generate_report(target_dir, db_matches_report, undetermined_count, duplicate_count):
    report_path = os.path.join(target_dir, "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("ОТЧЕТ О СООТВЕТСТВИИ СГРУППИРОВАННЫХ ЭКГ ШАБЛОНАМ БД\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"📊 СТАТИСТИКА ОБРАБОТКИ:\n")
        f.write(f"   - Найдено и скопировано дубликатов: {duplicate_count}\n")
        f.write(f"   - Неопределенные/ошибочные файлы: {undetermined_count}\n")
        f.write("-" * 70 + "\n\n")
        
        sorted_groups = sorted(db_matches_report.items(), key=lambda x: x[1]['count'], reverse=True)
        for cid, info in sorted_groups:
            f.write(f" Группа {cid} ({info['count']} файлов)\n")
            f.write(f"   👤 Совпадение: {info['match']}\n")
            f.write("-" * 70 + "\n")

if __name__ == "__main__":
    main()