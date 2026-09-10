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

from models import get_session, ECGRecord, ECGRaw, BiometricTemplate

MIN_RECORDS_FOR_TEMPLATE = 7      # Минимум для создания
OPTIMAL_RECORDS_FOR_TEMPLATE = 20 # Цель для максимальной точности
MAX_RECORDS_FOR_TEMPLATE = 50     # Предел (дальше — вытеснение старых)
BIOMETRIC_THRESHOLD = 0.30  # Порог срабатывания предупреждения


def _parse_and_clean_ecg(raw_data, fs=130.0):
    """Парсинг и очистка ЭКГ специально для биометрии (без медианного фильтра)."""
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
    """Извлекает форму и спектральные признаки."""
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
    """Анализирует записи, отбирает лучшие (до OPTIMAL_RECORDS_FOR_TEMPLATE шт.) и сохраняет шаблон в БД."""
    session = get_session(db_path)
    try:
        if progress_cb: progress_cb("Загрузка данных из БД...")
        
        # Берем ВСЕ доступные записи атлета
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

        # ⚡ Если записей больше MAX, берем только последние MAX (по порядку в БД = по дате)
        # Это защищает от устаревания шаблона и ускоряет расчет
        if len(valid_shapes) > MAX_RECORDS_FOR_TEMPLATE:
            valid_shapes = valid_shapes[-MAX_RECORDS_FOR_TEMPLATE:]
            valid_specs = valid_specs[-MAX_RECORDS_FOR_TEMPLATE:]
            if progress_cb: progress_cb(f"Используем последние {MAX_RECORDS_FOR_TEMPLATE} записей (всего валидных: {len(valid_shapes) + (len(raw_records) - len(valid_shapes))})...")

        # 1. Создаем черновой шаблон из ВСЕХ валидных записей (медиана устойчива к выбросам)
        draft_shape = np.median(valid_shapes, axis=0)
        
        # 2. Считаем расстояние каждой записи до чернового шаблона
        distances = [(i, dtw.distance_fast(shape.astype(np.double), draft_shape.astype(np.double))) 
                     for i, shape in enumerate(valid_shapes)]
        
        # Сортируем: сначала идут записи с наименьшим расстоянием (самые "чистые" и похожие)
        distances.sort(key=lambda x: x[1])
        
        # ⚡ Берем не строго MIN, а до OPTIMAL (но не больше, чем есть)
        num_to_use = min(OPTIMAL_RECORDS_FOR_TEMPLATE, len(valid_shapes))
        best_indices = [x[0] for x in distances[:num_to_use]]
        
        best_shapes = [valid_shapes[i] for i in best_indices]
        best_specs = [valid_specs[i] for i in best_indices]
        
        # 3. Финальный шаблон строится на основе этих лучших записей
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
        
        # Считаем среднее отклонение только для использованных записей
        avg_dist = sum(x[1] for x in distances[:num_to_use]) / num_to_use
        return True, f"Шаблон успешно создан из {len(best_shapes)} лучших записей (среднее отклонение: {avg_dist:.3f})"
        
    except Exception as e:
        session.rollback()
        return False, f"Ошибка: {str(e)}"
    finally:
        session.close()


def get_saved_template(db_path, athlete_id):
    """Возвращает (shape, spec) или (None, None), если шаблона нет."""
    session = get_session(db_path)
    try:
        tpl = session.query(BiometricTemplate).filter_by(athlete_id=athlete_id).first()
        if tpl:
            return np.array(json.loads(tpl.shape_template)), np.array(json.loads(tpl.spectrum_template))
        return None, None
    finally:
        session.close()


def check_ownership_with_saved_template(db_path, athlete_id, new_file_path):
    """Проверяет файл против СОХРАНЕННОГО шаблона."""
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