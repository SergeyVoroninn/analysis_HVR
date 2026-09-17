"""
ecg_biometrics.py — модуль биометрической проверки принадлежности ЭКГ.
"""
import os
import json
import numpy as np
from scipy.signal import find_peaks
from scipy import signal
from scipy.fft import fft, fftfreq
from dtaidistance import dtw

from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete

MIN_RECORDS_FOR_TEMPLATE = 7      
OPTIMAL_RECORDS_FOR_TEMPLATE = 20 
MAX_RECORDS_FOR_TEMPLATE = 50     
BIOMETRIC_THRESHOLD = 0.20  


def _parse_and_clean_ecg(raw_data, fs=130.0):
    lines = raw_data.split('\n')
    in_ecg, samples = False, []
    for line in lines:
        line = line.strip()
        if line == '[ECG]': in_ecg = True; continue
        if line.startswith('['): in_ecg = False; continue
        if in_ecg and ':' in line:
            try: samples.extend(int(v) for v in line.split(':', 1)[1].split(',') if v.strip())
            except ValueError: pass
    
    sig = np.asarray(samples, dtype=float)
    nyq = 0.5 * fs
    if 0 < 50.0 < nyq:
        b, a = signal.iirnotch(50.0 / nyq, Q=30.0)
        sig = signal.filtfilt(b, a, sig)
    if 0 < 0.5 < 50.0 < nyq:
        b, a = signal.butter(4, [0.5 / nyq, 50.0 / nyq], btype='band')
        sig = signal.filtfilt(b, a, sig)
    return sig


def _extract_features(ecg_clean, fs=130):
    min_r_height = np.mean(ecg_clean) + 1.5 * np.std(ecg_clean)
    rough_peaks, _ = find_peaks(ecg_clean, distance=int(0.3 * fs), height=min_r_height)
    window_samples, half_win = int(0.2 * fs), int(0.1 * fs)
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


def create_and_save_template(db_path, athlete_id, progress_cb=None):
    session = get_session(db_path)
    try:
        if progress_cb: progress_cb("Загрузка данных из БД...")
        raw_records = [row[0] for row in session.query(ECGRaw.raw_data)
                       .join(ECGRecord, ECGRaw.record_id == ECGRecord.id)
                       .filter(ECGRecord.athlete_id == athlete_id).all() if row[0]]
        
        if len(raw_records) < MIN_RECORDS_FOR_TEMPLATE:
            return False, f"Недостаточно записей. Нужно минимум {MIN_RECORDS_FOR_TEMPLATE}, найдено {len(raw_records)}."

        if progress_cb: progress_cb(f"Анализ {len(raw_records)} записей...")
        valid_shapes, valid_specs = [], []
        for raw in raw_records:
            try:
                shape, spec = _extract_features(_parse_and_clean_ecg(raw))
                if shape is not None and spec is not None:
                    valid_shapes.append(shape)
                    valid_specs.append(spec)
            except Exception:
                continue
                
        if len(valid_shapes) < MIN_RECORDS_FOR_TEMPLATE:
            return False, f"Слишком много записей с артефактами. Успешно обработано только {len(valid_shapes)}."

        if len(valid_shapes) > MAX_RECORDS_FOR_TEMPLATE:
            valid_shapes = valid_shapes[-MAX_RECORDS_FOR_TEMPLATE:]
            valid_specs = valid_specs[-MAX_RECORDS_FOR_TEMPLATE:]

        draft_shape = np.median(valid_shapes, axis=0)
        distances = [(i, dtw.distance_fast(shape.astype(np.double), draft_shape.astype(np.double))) 
                     for i, shape in enumerate(valid_shapes)]
        distances.sort(key=lambda x: x[1])
        
        num_to_use = min(OPTIMAL_RECORDS_FOR_TEMPLATE, len(valid_shapes))
        best_indices = [x[0] for x in distances[:num_to_use]]
        
        best_shapes = [valid_shapes[i] for i in best_indices]
        best_specs = [valid_specs[i] for i in best_indices]
        
        final_shape = np.median(best_shapes, axis=0)
        final_spec = np.median(best_specs, axis=0)
        
        if progress_cb: progress_cb("Сохранение в БД...")
        session.query(BiometricTemplate).filter_by(athlete_id=athlete_id).delete()
        new_template = BiometricTemplate(
            athlete_id=athlete_id,
            shape_template=json.dumps(final_shape.tolist()),
            spectrum_template=json.dumps(final_spec.tolist()),
            records_used=len(best_shapes)
        )
        session.add(new_template)
        session.commit()
        
        avg_dist = sum(x[1] for x in distances[:num_to_use]) / num_to_use
        return True, f"Шаблон успешно создан из {len(best_shapes)} лучших записей (среднее отклонение: {avg_dist:.3f})"
    except Exception as e:
        session.rollback()
        return False, f"Ошибка: {str(e)}"
    finally:
        session.close()


def get_saved_template(db_path, athlete_id):
    session = get_session(db_path)
    try:
        tpl = session.query(BiometricTemplate).filter_by(athlete_id=athlete_id).first()
        if tpl:
            return np.array(json.loads(tpl.shape_template)), np.array(json.loads(tpl.spectrum_template))
        return None, None
    finally:
        session.close()


def check_ownership_with_saved_template(db_path, athlete_id, new_file_path):
    ref_shape, ref_spec = get_saved_template(db_path, athlete_id)
    if ref_shape is None:
        return "NO_TEMPLATE", 9999, 0.0

    try:
        with open(new_file_path, 'r', encoding='utf-8') as f:
            new_raw = f.read()
        q_shape, q_spec = _extract_features(_parse_and_clean_ecg(new_raw))
    except Exception:
        return "ERROR", 9999, 0.0

    if q_shape is None or q_spec is None:
        return "BAD_SIGNAL", 9999, 0.0

    shape_dist = dtw.distance_fast(q_shape.astype(np.double), ref_shape.astype(np.double))
    spec_dist = np.sqrt(np.sum((q_spec - ref_spec) ** 2))
    
    distance = 0.6 * (shape_dist / 2.0) + 0.4 * (spec_dist / 0.5)
    probability = float(np.exp(-2.5 * distance))

    if distance > BIOMETRIC_THRESHOLD:
        return "SUSPICIOUS", distance, probability
    elif distance > 0.15:
        return "LOW_CONFIDENCE", distance, probability
    else:
        return "MATCH", distance, probability


# ==============================================================================
# НОВАЯ ФУНКЦИЯ: Поиск лучшего совпадения по всей базе
# ==============================================================================
def find_best_match(db_path, new_file_path, exclude_athlete_id=None):
    """
    Ищет атлета с наилучшим биометрическим совпадением.
    Для родственников использует более строгий порог.
    """
    try:
        with open(new_file_path, 'r', encoding='utf-8') as f:
            new_raw = f.read()
        q_shape, q_spec = _extract_features(_parse_and_clean_ecg(new_raw))
    except Exception:
        return None, 9999, 0.0, []

    if q_shape is None or q_spec is None:
        return None, 9999, 0.0, []

    session = get_session(db_path)
    try:
        results = session.query(BiometricTemplate, Athlete).join(
            Athlete, BiometricTemplate.athlete_id == Athlete.id
        ).all()

        matches = []
        for tpl, athlete in results:
            if exclude_athlete_id and athlete.id == exclude_athlete_id:
                continue
            
            try:
                ref_shape = np.array(json.loads(tpl.shape_template))
                ref_spec = np.array(json.loads(tpl.spectrum_template))
                
                shape_dist = dtw.distance_fast(q_shape.astype(np.double), ref_shape.astype(np.double))
                spec_dist = np.sqrt(np.sum((q_spec - ref_spec) ** 2))
                
                # 1. Проверка на родственника
                is_relative = _are_relatives_by_name(db_path, exclude_athlete_id, athlete.id)
                
                if is_relative:
                    # Для родственников форма QRS важнее, порог строже
                    distance = 0.7 * (shape_dist / 2.0) + 0.3 * (spec_dist / 0.5)
                    base_prob = float(np.exp(-3.5 * distance))
                else:
                    distance = 0.6 * (shape_dist / 2.0) + 0.4 * (spec_dist / 0.5)
                    base_prob = float(np.exp(-2.5 * distance))
                
                # ⚡ 2. НОВОЕ: Штраф за ненадежный шаблон (мало записей)
                # OPTIMAL_RECORDS_FOR_TEMPLATE = 20 (импортируйте это значение или задайте 20.0)
                optimal_records = 20.0
                records_used = max(1, tpl.records_used) # Защита от деления на 0
                
                # Коэффициент от 0.0 до 1.0. Если записей 20 и больше = 1.0. Если 7 = 0.35
                reliability_factor = min(1.0, records_used / optimal_records)
                
                # Дополнительный жесткий штраф, если записей критически мало (< 10)
                if records_used < 10:
                    reliability_factor *= 0.5 
                
                # Итоговая вероятность с учетом надежности шаблона
                final_prob = base_prob * reliability_factor
                
                matches.append({
                    'athlete': athlete,
                    'distance': distance,
                    'probability': final_prob,
                    'base_probability': base_prob, # Сохраняем для отладки/отображения
                    'records_used': records_used,
                    'is_relative': is_relative
                })
            except Exception:
                continue
        
        matches.sort(key=lambda x: x['probability'], reverse=True)
        
        if matches:
            best = matches[0]
            return best['athlete'], best['distance'], best['probability'], matches
        return None, 9999, 0.0, []
    finally:
        session.close()

def auto_update_template_if_needed(db_path, athlete_id):
    """
    Тихо проверяет количество записей атлета и обновляет шаблон, 
    если их стало достаточно (>= MIN_RECORDS_FOR_TEMPLATE).
    Работает в фоновом режиме, не блокируя интерфейс.
    """
    session = get_session(db_path)
    try:
        # Считаем количество записей
        count = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).count()
        
        if count >= MIN_RECORDS_FOR_TEMPLATE:
            # Запускаем создание/обновление шаблона без колбэков прогресса (тихо)
            create_and_save_template(db_path, athlete_id, progress_cb=None)
    except Exception:
        # Тихо игнорируем ошибки фонового обновления, чтобы не ломать импорт
        pass
    finally:
        session.close()

def _are_relatives_by_name(db_path, athlete_id_1, athlete_id_2):
    """Проверяет, являются ли атлеты родственниками по фамилии."""
    session = get_session(db_path)
    try:
        a1 = session.query(Athlete).filter_by(id=athlete_id_1).first()
        a2 = session.query(Athlete).filter_by(id=athlete_id_2).first()
        
        if not a1 or not a2:
            return False
        
        # Сравниваем фамилии (без учета регистра)
        return a1.last_name.lower() == a2.last_name.lower()
    finally:
        session.close()