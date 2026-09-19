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
from app_constants import BIOMETRIC_ERROR_DISTANCE
from models import get_session, ECGRecord, ECGRaw, BiometricTemplate, Athlete

# ==============================================================================
# КОНФИГУРАЦИЯ (Устранение хардкода и магических чисел)
# ==============================================================================
class ECGConfig:
    # --- Аппаратные параметры ---
    FS = 130.0                  # Частота дискретизации (Гц)
    NOTCH_FREQ = 50.0           # Частота сети (50.0 для РФ/Европы, 60.0 для США/Японии)
    BANDPASS_LOW = 0.5          # Нижняя граница фильтрации (Гц)
    BANDPASS_HIGH = 50.0        # Верхняя граница фильтрации (Гц)
    NOTCH_Q = 30.0              # Добротность режекторного фильтра
    BUTTERWORTH_ORDER = 4       # Порядок фильтра Баттерворта

    # --- Параметры извлечения признаков (в секундах, масштабируются под FS) ---
    R_PEAK_STD_MULT = 1.5       # Множитель стандартного отклонения для порога R-зубца
    PEAK_DISTANCE_SEC = 0.3     # Мин. расстояние между пиками (сек)
    WINDOW_SEC = 0.2            # Ширина окна цикла (сек)
    HALF_WINDOW_SEC = 0.1       # Половина окна цикла (сек)
    BASELINE_SEC = 0.05         # Окно для оценки базовой линии перед R-зубцом (сек)
    LOCAL_R_SEARCH_SEC = 0.08   # Окно поиска истинного пика R (вместо жестких 10 семплов)

    # --- Веса и нормализация для сравнения (Обычные пользователи) ---
    SHAPE_WEIGHT = 0.6
    SPEC_WEIGHT = 0.4
    SHAPE_NORM_FACTOR = 2.0     # Делитель для нормализации DTW расстояния формы
    SPEC_NORM_FACTOR = 0.5      # Делитель для нормализации евклидова расстояния спектра
    PROB_DECAY_NORMAL = 2.5     # Коэффициент затухания вероятности

    # --- Веса и нормализация для родственников ---
    REL_SHAPE_WEIGHT = 0.7
    REL_SPEC_WEIGHT = 0.3
    PROB_DECAY_RELATIVE = 3.5

    # --- Пороги и лимиты ---
    MIN_RECORDS = 9      
    OPTIMAL_RECORDS = 20 
    MAX_RECORDS = 50     
    BIOMETRIC_THRESHOLD = 0.15  
    MATCH_WARNING_THRESHOLD = 0.10

    # --- Бонусы за надежность шаблона ---
    RELIABILITY_HIGH_THRESH = 20
    RELIABILITY_LOW_THRESH = 10
    RELIABILITY_BONUS_HIGH = 0.10  # +10%
    RELIABILITY_BONUS_LOW = 0.05   # +5%

# Глобальный экземпляр конфигурации (можно переопределить при необходимости)
cfg = ECGConfig()


def _parse_and_clean_ecg(raw_data, fs=None):
    fs = fs or cfg.FS
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
                samples.extend(int(v) for v in line.split(':', 1)[1].split(',') if v.strip())
            except ValueError: 
                pass
    
    sig = np.asarray(samples, dtype=float)
    nyq = 0.5 * fs
    
    # Режекторный фильтр (сеть)
    if 0 < cfg.NOTCH_FREQ < nyq:
        b, a = signal.iirnotch(cfg.NOTCH_FREQ / nyq, Q=cfg.NOTCH_Q)
        sig = signal.filtfilt(b, a, sig)
        
    # Полосовой фильтр
    if 0 < cfg.BANDPASS_LOW < cfg.BANDPASS_HIGH < nyq:
        b, a = signal.butter(cfg.BUTTERWORTH_ORDER, [cfg.BANDPASS_LOW / nyq, cfg.BANDPASS_HIGH / nyq], btype='band')
        sig = signal.filtfilt(b, a, sig)
        
    return sig


def _extract_features(ecg_clean, fs=None):
    fs = fs or cfg.FS
    min_r_height = np.mean(ecg_clean) + cfg.R_PEAK_STD_MULT * np.std(ecg_clean)
    
    # Переводим временные интервалы в семплы динамически
    peak_distance_samples = int(cfg.PEAK_DISTANCE_SEC * fs)
    window_samples = int(cfg.WINDOW_SEC * fs)
    half_win = int(cfg.HALF_WINDOW_SEC * fs)
    baseline_samples = max(1, int(cfg.BASELINE_SEC * fs))
    local_r_search_samples = max(1, int(cfg.LOCAL_R_SEARCH_SEC * fs))
    
    rough_peaks, _ = find_peaks(ecg_clean, distance=peak_distance_samples, height=min_r_height)
    shape_cycles, spectral_features = [], []
    
    for rough_peak in rough_peaks:
        if rough_peak - half_win > 0 and rough_peak + half_win < len(ecg_clean):
            cycle = ecg_clean[rough_peak - half_win : rough_peak + half_win].copy()
            center = half_win
            
            # Динамический поиск локального максимума вместо жестких +/- 10 семплов
            search_start = max(0, center - local_r_search_samples)
            search_end = min(len(cycle), center + local_r_search_samples)
            local_region = cycle[search_start : search_end]
            
            r_offset = np.argmax(local_region) - (center - search_start)
            if r_offset != 0: 
                cycle = np.roll(cycle, -r_offset)
            
            r_value, baseline = cycle[center], np.min(cycle[:baseline_samples])
            if abs(r_value - baseline) > 1e-8:
                r_norm = (cycle - baseline) / (r_value - baseline)
                shape_cycles.append(r_norm)
                
                yf, xf = fft(cycle), fftfreq(len(cycle), 1/fs)
                xf_pos, yf_pos = xf[xf > 0], np.abs(yf[xf > 0])
                if np.max(yf_pos) > 1e-8: 
                    yf_pos /= np.max(yf_pos)
                
                dom_freq = xf_pos[np.argmax(yf_pos[1:]) + 1] if len(yf_pos) > 1 else 0
                
                # Динамические маски частот (можно вынести в конфиг, если потребуется гибкость)
                masks = [
                    (xf_pos >= 5) & (xf_pos < 15), 
                    (xf_pos >= 15) & (xf_pos < 30), 
                    (xf_pos >= 30) & (xf_pos < 50)
                ]
                energies = [np.trapezoid(yf_pos[m], xf_pos[m]) if np.any(m) else 0 for m in masks]
                total = sum(energies)
                if total > 1e-8: 
                    energies = [e/total for e in energies]
                    
                # Нормализация доминирующей частоты относительно верхней границы фильтра
                spectral_features.append([dom_freq / cfg.BANDPASS_HIGH] + energies)

    if len(shape_cycles) < 3 or len(spectral_features) < 3: 
        return None, None
    return np.median(shape_cycles, axis=0), np.median(spectral_features, axis=0)


def create_and_save_template(db_path, athlete_id, progress_cb=None):
    session = get_session(db_path)
    try:
        if progress_cb: progress_cb("Загрузка данных из БД...")
        raw_records = [row[0] for row in session.query(ECGRaw.raw_data)
                       .join(ECGRecord, ECGRaw.record_id == ECGRecord.id)
                       .filter(ECGRecord.athlete_id == athlete_id).all() if row[0]]
        
        if len(raw_records) < cfg.MIN_RECORDS:
            return False, f"Недостаточно записей. Нужно минимум {cfg.MIN_RECORDS}, найдено {len(raw_records)}."

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
                
        if len(valid_shapes) < cfg.MIN_RECORDS:
            return False, f"Слишком много записей с артефактами. Успешно обработано только {len(valid_shapes)}."

        if len(valid_shapes) > cfg.MAX_RECORDS:
            valid_shapes = valid_shapes[-cfg.MAX_RECORDS:]
            valid_specs = valid_specs[-cfg.MAX_RECORDS:]

        draft_shape = np.median(valid_shapes, axis=0)
        distances = [(i, dtw.distance_fast(shape.astype(np.double), draft_shape.astype(np.double))) 
                     for i, shape in enumerate(valid_shapes)]
        distances.sort(key=lambda x: x[1])
        
        num_to_use = min(cfg.OPTIMAL_RECORDS, len(valid_shapes))
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
        return "NO_TEMPLATE", BIOMETRIC_ERROR_DISTANCE, 0.0

    try:
        with open(new_file_path, 'r', encoding='utf-8') as f:
            new_raw = f.read()
        q_shape, q_spec = _extract_features(_parse_and_clean_ecg(new_raw))
    except Exception:
        return "ERROR", BIOMETRIC_ERROR_DISTANCE, 0.0

    if q_shape is None or q_spec is None:
        return "BAD_SIGNAL", BIOMETRIC_ERROR_DISTANCE, 0.0

    shape_dist = dtw.distance_fast(q_shape.astype(np.double), ref_shape.astype(np.double))
    spec_dist = np.sqrt(np.sum((q_spec - ref_spec) ** 2))
    
    # Используем конфигурационные веса и нормализаторы
    distance = cfg.SHAPE_WEIGHT * (shape_dist / cfg.SHAPE_NORM_FACTOR) + \
               cfg.SPEC_WEIGHT * (spec_dist / cfg.SPEC_NORM_FACTOR)
               
    probability = float(np.exp(-cfg.PROB_DECAY_NORMAL * distance))

    if distance > cfg.BIOMETRIC_THRESHOLD:
        return "SUSPICIOUS", distance, probability
    else:
        return "MATCH", distance, probability


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
        return None, BIOMETRIC_ERROR_DISTANCE, 0.0, []

    if q_shape is None or q_spec is None:
        return None, BIOMETRIC_ERROR_DISTANCE, 0.0, []

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
                
                is_relative = _are_relatives_by_name(db_path, exclude_athlete_id, athlete.id)
                
                if is_relative:
                    distance = cfg.REL_SHAPE_WEIGHT * (shape_dist / cfg.SHAPE_NORM_FACTOR) + \
                               cfg.REL_SPEC_WEIGHT * (spec_dist / cfg.SPEC_NORM_FACTOR)
                    base_prob = float(np.exp(-cfg.PROB_DECAY_RELATIVE * distance))
                else:
                    distance = cfg.SHAPE_WEIGHT * (shape_dist / cfg.SHAPE_NORM_FACTOR) + \
                               cfg.SPEC_WEIGHT * (spec_dist / cfg.SPEC_NORM_FACTOR)
                    base_prob = float(np.exp(-cfg.PROB_DECAY_NORMAL * distance))
                
                records_used = max(1, tpl.records_used)
                
                reliability_bonus = 0.0
                if records_used >= cfg.RELIABILITY_HIGH_THRESH:
                    reliability_bonus = cfg.RELIABILITY_BONUS_HIGH
                elif records_used >= cfg.RELIABILITY_LOW_THRESH:
                    reliability_bonus = cfg.RELIABILITY_BONUS_LOW
                
                final_prob = min(1.0, base_prob * (1.0 + reliability_bonus))
                
                matches.append({
                    'athlete': athlete,
                    'distance': distance,
                    'probability': final_prob,
                    'base_probability': base_prob,
                    'records_used': records_used,
                    'is_relative': is_relative
                })
            except Exception:
                continue
        
        matches.sort(key=lambda x: x['distance'])
        
        if matches:
            best = matches[0]
            return best['athlete'], best['distance'], best['probability'], matches
        return None, BIOMETRIC_ERROR_DISTANCE, 0.0, []
    finally:
        session.close()


def auto_update_template_if_needed(db_path, athlete_id):
    session = get_session(db_path)
    try:
        count = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).count()
        if count >= cfg.MIN_RECORDS:
            create_and_save_template(db_path, athlete_id, progress_cb=None)
    except Exception:
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
        
        # ВНИМАНИЕ: Это бизнес-правило (хардкод логики). 
        # Оно не сработает для матери/детей с разными фамилиями или однофамильцев, не являющихся родственниками.
        # Если потребуется, эту логику нужно вынести в отдельное поле is_relative в БД.
        return a1.last_name.lower() == a2.last_name.lower()
    finally:
        session.close()