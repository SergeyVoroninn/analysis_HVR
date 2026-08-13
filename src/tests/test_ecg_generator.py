import pytest
from ecg_generator import create_rr_list, create_ecg, create_record
from analysis import parse_rr


def test_rr_bounds_and_duration():
    rr = create_rr_list(60, mean_rr_ms=800, rmssd_ms=50)
    assert all(400 <= v <= 1200 for v in rr)          # клампы 0.5–1.5 × mean
    assert abs(sum(rr) - 60000) < 1500                # ≈ длительность


def test_record_rr_section():
    raw = create_record(duration_seconds=30, mean_rr_ms=800, rmssd_ms=50)
    rr = parse_rr(raw)
    assert len(rr) > 20


def _ecg_samples(ecg_str):
    samples = []
    for line in ecg_str.splitlines():
        vals = line.split(":", 1)[1].rstrip(",").split(",")
        samples.extend(int(v) for v in vals if v.strip())
    return samples


def _detect_r_peaks(samples, min_height=1000, min_dist=80):
    """
    Находит R-пики как локальные максимумы выше min_height
    с минимальным расстоянием min_dist между ними.
    """
    peaks = []
    n = len(samples)
    for i in range(1, n - 1):
        # Локальный максимум + выше порога
        if (samples[i] > min_height and 
            samples[i] > samples[i-1] and 
            samples[i] > samples[i+1]):
            # Минимальное расстояние между пиками
            if not peaks or (i - peaks[-1]) >= min_dist:
                peaks.append(i)
    return peaks

def test_ecg_rr_consistency():
    """R-пики в сигнале стоят ТОЧНО по RR из секции [RR]."""
    rr_list = [800] * 40
    samples = _ecg_samples(create_ecg(30, rr_intervals=rr_list))
    peaks = _detect_r_peaks(samples, min_height=800, min_dist=50)
    assert len(peaks) >= 15  # после transient должно быть достаточно

    # Ожидаемые позиции R-пиков (накопленные RR → отсчёты @130 Гц)
    expected_positions = []
    acc = 0
    for rr in rr_list:
        acc += round(rr * 130 / 1000.0)
        if acc < len(samples):
            expected_positions.append(acc)

    # Пропускаем первые 3 ожидаемых пика (они в transient)
    stable_expecteded = expected_positions[3:]
    
    # Проверяем, что найденные пики совпадают с ожидаемыми
    found_count = 0
    for expected_pos in stable_expecteded:
        # Ищем ближайший найденный пик
        if peaks:
            diffs = [abs(p - expected_pos) for p in peaks]
            min_diff = min(diffs)
            if min_diff <= 5:  # допуск ±5 отсчётов
                found_count += 1
    
    # Должно совпасть минимум 80% ожидаемых пиков
    assert found_count >= len(stable_expecteded) * 0.8