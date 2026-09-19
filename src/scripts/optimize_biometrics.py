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

# Добавляем путь к корню проекта, чтобы работали абсолютные импорты
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(script_dir))

try:
    from database import get_db_path
    from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete
    # ИМПОРТИРУЕМ функции и конфиг напрямую, чтобы не дублировать код!
    from ecg_biometrics import _parse_and_clean_ecg, _extract_features, cfg
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что запускаете скрипт из папки scripts или настроили PYTHONPATH.")
    sys.exit(1)

def main():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена по пути: {db_path}")
        print("💡 Убедитесь, что основное приложение было запущено хотя бы раз.")
        sys.exit(1)

    print(f"🔍 Подключение к базе данных: {db_path}")
    session = get_session(db_path)
    
    # 1. Загружаем все шаблоны
    print("📥 Загрузка шаблонов...")
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

    # 2. Загружаем все записи и извлекаем признаки
    print("⚙️ Извлечение признаков из всех записей в БД...")
    records_data = []
    all_raw = session.query(ECGRecord.athlete_id, ECGRaw.raw_data).join(ECGRaw, ECGRecord.id == ECGRaw.record_id).all()
    
    valid_count = 0
    for ath_id, raw_data in all_raw:
        if ath_id not in templates:
            continue
        
        clean_ecg = _parse_and_clean_ecg(raw_data)
        if len(clean_ecg) == 0:
            continue
            
        shape, spec = _extract_features(clean_ecg)
        if shape is not None and spec is not None:
            records_data.append({'athlete_id': ath_id, 'shape': shape, 'spec': spec})
            valid_count += 1
            
    print(f"   ✅ Успешно обработано записей: {valid_count}")

    # 3. Предварительный расчет "сырых" расстояний
    print("📏 Предварительный расчет матрицы расстояний...")
    precalculated_dists = []
    for rec in records_data:
        rec_dists = {}
        for tpl_ath_id, tpl_data in templates.items():
            try:
                s_dist = dtw.distance_fast(rec['shape'].astype(np.double), tpl_data['shape'].astype(np.double))
                sp_dist = np.sqrt(np.sum((rec['spec'] - tpl_data['spec']) ** 2))
                rec_dists[tpl_ath_id] = (s_dist, sp_dist)
            except Exception:
                rec_dists[tpl_ath_id] = (10.0, 10.0)
        precalculated_dists.append((rec['athlete_id'], rec_dists))

    # 4. GRID SEARCH
    print("\n🚀 Запуск Grid Search по параметрам...")
    thresholds = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    w_shapes = [0.5, 0.6, 0.7, 0.8]
    
    results = []
    for thresh, w_s in product(thresholds, w_shapes):
        w_sp = 1.0 - w_s
        tp = fn = tn = fp = 0

        for true_ath_id, rec_dists in precalculated_dists:
            best_match_id = None
            min_combined_dist = float('inf')
            
            for tpl_ath_id, (s_dist, sp_dist) in rec_dists.items():
                # Используем те же нормализаторы, что и в основном коде (2.0 и 0.5)
                combined_dist = w_s * (s_dist / cfg.SHAPE_NORM_FACTOR) + w_sp * (sp_dist / cfg.SPEC_NORM_FACTOR)
                if combined_dist < min_combined_dist:
                    min_combined_dist = combined_dist
                    best_match_id = tpl_ath_id

            if best_match_id == true_ath_id:
                if min_combined_dist <= thresh: tp += 1
                else: fn += 1
            else:
                if min_combined_dist <= thresh: fp += 1
                else: tn += 1

        total_checks = tp + fn + tn + fp
        accuracy = (tp + tn) / total_checks if total_checks > 0 else 0
        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        tnr = tn / (tn + fp) if (tn + fp) > 0 else 0
        balanced_acc = (tpr + tnr) / 2.0

        results.append({
            'threshold': thresh, 'w_shape': w_s, 'w_spec': round(w_sp, 1),
            'accuracy': accuracy, 'tpr': tpr, 'tnr': tnr, 'balanced_acc': balanced_acc
        })

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
    
    best = results[0]
    print(f"\n💡 РЕКОМЕНДАЦИЯ:")
    print(f"   Обновите в ecg_biometrics.py (класс ECGConfig):")
    print(f"   BIOMETRIC_THRESHOLD = {best['threshold']}")
    print(f"   SHAPE_WEIGHT = {best['w_shape']}")
    print(f"   SPEC_WEIGHT = {best['w_spec']}")
    print(f"   (Ожидаемая сбалансированная точность: ~{best['balanced_acc']*100:.1f}%)")

    session.close()

if __name__ == "__main__":
    main()