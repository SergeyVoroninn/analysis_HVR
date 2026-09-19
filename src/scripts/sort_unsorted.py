"""
sort_unsorted.py — скрипт для кластеризации неизвестных ЭКГ-записей, 
поиска дубликатов, сопоставления с БД и финального объединения по атлетам.

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
from scipy.cluster.hierarchy import linkage, fcluster
from dtaidistance import dtw
from collections import Counter

# ==============================================================================
# 1. СНАЧАЛА добавляем корневую папку проекта (src) в пути поиска модулей
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
# Добавляем родительскую директорию (src) в начало sys.path
sys.path.insert(0, os.path.dirname(script_dir))

# ==============================================================================
# 2. ТОЛЬКО ТЕПЕРЬ импортируем локальные модули из папки src
# ==============================================================================
try:
    from app_constants import (
        SORT_LARGE_GROUP_THRESHOLD, 
        SORT_STRICT_THRESHOLD, 
        BIOMETRIC_ERROR_DISTANCE,
        ECG_FILE_EXTENSION
    )
except ImportError:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось найти файл 'app_constants.py' в папке src.")
    print("Убедитесь, что он создан и содержит необходимые константы.")
    sys.exit(1)

try:
    # ЦЕНТРАЛИЗОВАННЫЙ ИМПОРТ: Путь к БД, модели и алгоритмы биометрии
    from database import get_db_path
    from models import get_session, BiometricTemplate, Athlete
    from ecg_biometrics import _parse_and_clean_ecg, _extract_features, cfg
    MODELS_AVAILABLE = True
except ImportError as e:
    MODELS_AVAILABLE = False
    print(f"⚠️ Предупреждение: Не удалось импортировать модули ({e}). Сопоставление с БД будет пропущено.")

# ==============================================================================
# НАСТРОЙКИ СКРИПТА (Только те, что не вынесены в app_constants)
# ==============================================================================
MIN_GROUP_SIZE = 3  # Группы меньше этого размера идут в undetermined
# Используем константу из app_constants + возможное расширение .txt для совместимости
SUPPORTED_EXTENSIONS = (ECG_FILE_EXTENSION, '.txt')

def get_file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def calculate_distance(data1, data2):
    """Расчет расстояния с использованием весов и нормализации из центрального конфига."""
    try:
        shape_dist = dtw.distance_fast(data1['shape'].astype(np.double), data2['shape'].astype(np.double))
        spec_dist = np.sqrt(np.sum((data1['spec'] - data2['spec']) ** 2))
        
        # ИСПОЛЬЗУЕМ cfg для 100% синхронизации с приложением
        dist = cfg.SHAPE_WEIGHT * (shape_dist / cfg.SHAPE_NORM_FACTOR) + \
               cfg.SPEC_WEIGHT * (spec_dist / cfg.SPEC_NORM_FACTOR)
               
        if not np.isfinite(dist):
            return BIOMETRIC_ERROR_DISTANCE  # ✅ ИСПРАВЛЕНО: была несуществующая MAX_PENALTY
        return float(dist)
    except Exception:
        return BIOMETRIC_ERROR_DISTANCE      # ✅ ИСПРАВЛЕНО: был хардкод 10.0

def main():
    parser = argparse.ArgumentParser(description="Кластеризация и сопоставление ЭКГ с БД")
    parser.add_argument("source_folder", help="Имя исходной папки с файлами")
    parser.add_argument("--db", dest="db_path", help="Путь к файлу БД (по умолчанию используется системный get_db_path())", default=None)
    args = parser.parse_args()

    source_dir = os.path.join(script_dir, args.source_folder)
    if not os.path.isdir(source_dir):
        print(f"❌ Ошибка: исходная папка '{source_dir}' не найдена.")
        sys.exit(1)

    target_dir = os.path.join(os.path.dirname(source_dir), "sorted")
    
    if os.path.exists(target_dir):
        print(f"🧹 Очистка предыдущих результатов в: {target_dir}")
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    print(f"📁 Результаты будут сохранены в: {target_dir}")
    print(f"🔒 Исходная папка '{source_dir}' остается неизменной.\n")

    all_files = [f for f in os.listdir(source_dir) if f.lower().endswith(SUPPORTED_EXTENSIONS)]
    print(f"Найдено файлов для обработки: {len(all_files)}")

    # ==========================================================================
    # ЭТАП 0: Поиск дубликатов
    # ==========================================================================
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
            shutil.copy2(dup_path, os.path.join(dup_dir, os.path.basename(dup_path)))
        print(f"  📂 Дубликаты скопированы в: {dup_dir}")

    all_files = [os.path.basename(f) for f in unique_files]
    undetermined_files = []
    valid_files_data = []

    # ==========================================================================
    # ЭТАП 1: Извлечение признаков (Используем импортированные функции)
    # ==========================================================================
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
        generate_report(target_dir, {}, len(undetermined_files) + len(valid_files_data), len(duplicate_files), {})
        return

    # ==========================================================================
    # ЭТАП 2: Матрица расстояний
    # ==========================================================================
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
    labels = fcluster(Z, t=cfg.BIOMETRIC_THRESHOLD, criterion='distance')

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
    athlete_consolidation = {} 
    
    actual_db_path = args.db_path if args.db_path else get_db_path()
    db_templates = []
    
    if MODELS_AVAILABLE and os.path.exists(actual_db_path):
        print(f"  🔍 Загрузка шаблонов из БД: {actual_db_path}")
        session = get_session(actual_db_path)
        db_templates = session.query(BiometricTemplate, Athlete).join(Athlete).all()
        print(f"  Найдено шаблонов в БД: {len(db_templates)}")
    else:
        if MODELS_AVAILABLE:
            print(f"  ⚠️ База данных не найдена по пути: {actual_db_path}. Сопоставление пропущено.")
        else:
            print("  ⚠️ Модули БД недоступны. Сопоставление пропущено.")

    copied_count = 0
    small_group_files = []
    final_groups = {}
    group_counter = 1000

    for cid, group_files in groups.items():
        if len(group_files) < MIN_GROUP_SIZE:
            small_group_files.extend(group_files)
            continue

        # ✅ ИСПРАВЛЕНО: Используем импортированную константу SORT_LARGE_GROUP_THRESHOLD
        if len(group_files) >= SORT_LARGE_GROUP_THRESHOLD and db_templates:
            print(f"  🔎 Группа {cid} большая ({len(group_files)} файлов). Пробую разделить на подгруппы...")
            n_sub = len(group_files)
            sub_dist_matrix = []
            for i in range(n_sub):
                for j in range(i + 1, n_sub):
                    dist = calculate_distance(group_files[i], group_files[j])
                    sub_dist_matrix.append(dist)
            
            Z_sub = linkage(sub_dist_matrix, method='average')
            # ✅ ИСПРАВЛЕНО: Используем импортированную константу SORT_STRICT_THRESHOLD
            sub_labels = fcluster(Z_sub, t=SORT_STRICT_THRESHOLD, criterion='distance')
            sub_cluster_sizes = Counter(sub_labels)
            
            valid_sub_groups = [sub_id for sub_id, count in sub_cluster_sizes.items() if count >= MIN_GROUP_SIZE]
            
            if len(valid_sub_groups) >= 2:
                print(f"     ✅ Успешно разделена на {len(valid_sub_groups)} подгрупп!")
                for sub_id in valid_sub_groups:
                    new_cid = group_counter
                    group_counter += 1
                    final_groups[new_cid] = [group_files[i] for i in range(n_sub) if sub_labels[i] == sub_id]
                continue
            else:
                print(f"     ⚠️ Не удалось разделить строже. Оставляю как одну группу.")

        final_groups[cid] = group_files

    # Обработка финальных групп
    for cid, group_files in final_groups.items():
        group_folder_name = f"group_{cid}"
        group_folder_path = os.path.join(target_dir, group_folder_name)
        os.makedirs(group_folder_path, exist_ok=True)

        for file_info in group_files:
            dest = os.path.join(group_folder_path, file_info['filename'])
            if not os.path.exists(dest):
                shutil.copy2(file_info['filepath'], dest)
                copied_count += 1

        best_match_name = "Неизвестно"
        min_dist = float('inf')
        matched_athlete = None
        
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
                        matched_athlete = athlete
                except Exception:
                    continue
        
        if min_dist <= cfg.BIOMETRIC_THRESHOLD and matched_athlete:
            best_match_name = f"✅ {best_match_name} (расстояние: {min_dist:.3f})"
            
            ath_id = matched_athlete.id
            if ath_id not in athlete_consolidation:
                athlete_consolidation[ath_id] = {
                    'name': f"{matched_athlete.last_name}_{matched_athlete.first_name}",
                    'files': [],
                    'groups': []
                }
            athlete_consolidation[ath_id]['files'].extend([f['filepath'] for f in group_files])
            athlete_consolidation[ath_id]['groups'].append(cid)
        else:
            best_match_name = f"Неизвестно (мин. расстояние: {min_dist:.3f} > порога {cfg.BIOMETRIC_THRESHOLD})"

        db_matches_report[cid] = {'count': len(group_files), 'match': best_match_name}

    if small_group_files:
        print(f"  ⚠️ Группы с < {MIN_GROUP_SIZE} файлами ({len(small_group_files)} файлов) отправлены в undetermined")
        for file_info in small_group_files:
            undetermined_files.append(file_info['filepath'])

    copy_to_undetermined(source_dir, target_dir, undetermined_files)

    # ==========================================================================
    # ЭТАП 5: Финальное объединение по атлетам
    # ==========================================================================
    print("Этап 5: Финальное объединение файлов по атлетам...")
    consolidated_count = 0
    consolidation_report = {}
    
    for ath_id, data in athlete_consolidation.items():
        safe_name = data['name'].replace(' ', '_')
        folder_name = f"athlete_{safe_name}_{ath_id[:4]}"
        folder_path = os.path.join(target_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        for filepath in data['files']:
            filename = os.path.basename(filepath)
            dest = os.path.join(folder_path, filename)
            if not os.path.exists(dest):
                shutil.copy2(filepath, dest)
                consolidated_count += 1
                
        consolidation_report[folder_name] = {
            'count': len(data['files']),
            'groups': data['groups']
        }
        print(f"  📂 Создана: {folder_name} ({len(data['files'])} файлов из групп {data['groups']})")

    generate_report(target_dir, db_matches_report, len(undetermined_files), len(duplicate_files), consolidation_report)

    print("\n✅ Сортировка и анализ завершены!")
    print(f"   🗑️ Скопировано дубликатов: {len(duplicate_files)}")
    print(f"   📂 Скопировано в детальные группы: {copied_count}")
    print(f"   📁 Создано итоговых папок атлетов: {len(consolidation_report)} (всего {consolidated_count} файлов)")
    print(f"   ❓ Отправлено в undetermined: {len(undetermined_files)}")
    print(f"   🔒 Исходная папка не изменена.")
    print(f"   📝 Отчет сохранен в: {os.path.join(target_dir, 'report.txt')}")


def copy_to_undetermined(source_dir, target_dir, filepaths):
    if not filepaths:
        return
    undetermined_dir = os.path.join(target_dir, "undetermined")
    os.makedirs(undetermined_dir, exist_ok=True)
    for filepath in filepaths:
        filename = os.path.basename(filepath)
        dest = os.path.join(undetermined_dir, filename)
        if os.path.exists(filepath) and not os.path.exists(dest):
            shutil.copy2(filepath, dest)

def generate_report(target_dir, db_matches_report, undetermined_count, duplicate_count, consolidation_report):
    report_path = os.path.join(target_dir, "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("ОТЧЕТ О СООТВЕТСТВИИ СГРУППИРОВАННЫХ ЭКГ ШАБЛОНАМ БД\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"📊 СТАТИСТИКА ОБРАБОТКИ:\n")
        f.write(f"   - Найдено и скопировано дубликатов: {duplicate_count}\n")
        f.write(f"   - Неопределенные/ошибочные файлы: {undetermined_count}\n")
        f.write("-" * 70 + "\n\n")
        
        f.write("📋 ДЕТАЛЬНАЯ КЛАСТЕРИЗАЦИЯ:\n")
        sorted_groups = sorted(db_matches_report.items(), key=lambda x: x[1]['count'], reverse=True)
        for cid, info in sorted_groups:
            f.write(f" Группа {cid} ({info['count']} файлов)\n")
            f.write(f"   👤 Совпадение: {info['match']}\n")
            f.write("-" * 70 + "\n")
            
        f.write("\n" + "=" * 70 + "\n")
        f.write("📁 ИТОГОВЫЕ ПАПКИ АТЛЕТОВ (Объединенные):\n")
        f.write("=" * 70 + "\n")
        if consolidation_report:
            for folder_name, info in sorted(consolidation_report.items(), key=lambda x: x[1]['count'], reverse=True):
                f.write(f"📂 {folder_name} ({info['count']} файлов)\n")
                f.write(f"   📌 Включает детальные группы: {', '.join(map(str, info['groups']))}\n")
                f.write("-" * 70 + "\n")
        else:
            f.write("   (Не найдено надежных совпадений для объединения)\n")

if __name__ == "__main__":
    main()