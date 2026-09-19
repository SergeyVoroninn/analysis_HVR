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
    from database import get_db_path
    from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete
    # ИМПОРТИРУЕМ функции и конфиг напрямую для 100% синхронизации с приложением
    from ecg_biometrics import _parse_and_clean_ecg, _extract_features, cfg
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что запускаете скрипт из папки scripts или настроили PYTHONPATH.")
    sys.exit(1)

def main():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        sys.exit(1)

    print(f"🔍 Загрузка данных из: {db_path}")
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
            records_data.append({'athlete_id': ath_id, 'shape': shape, 'spec': spec})

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
                
                # ИСПОЛЬЗУЕМ КОНФИГ для 100% соответствия логике приложения
                combined_dist = cfg.SHAPE_WEIGHT * (s_dist / cfg.SHAPE_NORM_FACTOR) + \
                                cfg.SPEC_WEIGHT * (sp_dist / cfg.SPEC_NORM_FACTOR)
                
                if not np.isfinite(combined_dist) or combined_dist > 5.0:
                    if rec['athlete_id'] == tpl_ath_id: inf_count_own += 1
                    else: inf_count_other += 1
                    continue
                
                if rec['athlete_id'] == tpl_ath_id:
                    own_distances.append(combined_dist)
                else:
                    other_distances.append(combined_dist)
            except Exception:
                if rec['athlete_id'] == tpl_ath_id: inf_count_own += 1
                else: inf_count_other += 1

    print(f"\n📊 Статистика расстояний (ТОЛЬКО ВАЛИДНЫЕ ДАННЫЕ):")
    print(f"   Свои пары: {len(own_distances)} (пропущено битых: {inf_count_own})")
    if own_distances:
        print(f"   Среднее: {np.mean(own_distances):.3f} | Медиана: {np.median(own_distances):.3f} | Std: {np.std(own_distances):.3f}")
    
    print(f"   Чужие пары: {len(other_distances)} (пропущено битых: {inf_count_other})")
    if other_distances:
        print(f"   Среднее: {np.mean(other_distances):.3f} | Медиана: {np.median(other_distances):.3f} | Std: {np.std(other_distances):.3f}")

    if own_distances and other_distances:
        plt.figure(figsize=(12, 6))
        plt.hist(own_distances, bins=50, alpha=0.6, label=f'Свои (n={len(own_distances)})', color='green', density=True)
        plt.hist(other_distances, bins=50, alpha=0.6, label=f'Чужие (n={len(other_distances)})', color='red', density=True)
        plt.xlabel('Расстояние')
        plt.ylabel('Плотность')
        plt.title('Распределение расстояний: свои vs чужие')
        plt.legend()
        plt.xlim(0, 1.0)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig('distance_distribution.png', dpi=150)
        print(f"\n📈 График сохранен: distance_distribution.png")

    print(f"\n🔍 Анализ точности при разных порогах (текущие веса: Shape={cfg.SHAPE_WEIGHT}, Spec={cfg.SPEC_WEIGHT}):")
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
    print(f"   Оптимальный порог для текущих весов: {best_thresh}")
    print(f"   Ожидаемая сбалансированная точность: {best_score*100:.1f}%")
    if inf_count_own > len(own_distances) * 0.1:
        print(f"   ⚠️ ВНИМАНИЕ: {inf_count_own} записей ('своих') дают сбой расчета (inf).")
        print(f"   Это может быть причиной низкой точности. Проверьте качество этих записей.")

    session.close()

if __name__ == "__main__":
    main()