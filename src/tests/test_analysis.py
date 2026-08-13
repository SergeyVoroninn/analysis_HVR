import pytest
from analysis import parse_rr, calc_metrics, calc_stress, stress_level


def test_parse_rr():
    raw = "[RR]\n800,810,790"
    assert parse_rr(raw) == [800, 810, 790]


def test_metrics_constant_rr():
    """Постоянный ритм → нулевая вариабельность, ЧСС = 60000/RR."""
    m = calc_metrics([800] * 100)
    assert m["mean_hr"] == pytest.approx(75.0, abs=0.5)
    assert m["rmssd"] == pytest.approx(0.0, abs=1e-6)
    assert m["sdnn"] == pytest.approx(0.0, abs=1e-6)


def test_metrics_known_rmssd():
    """Чередование 700/900 → все соседние различия = 200 → RMSSD = 200."""
    m = calc_metrics([700, 900] * 50)
    assert m["rmssd"] == pytest.approx(200.0, abs=1.0)


def test_stress_returns_si():
    s = calc_stress([800, 810, 790, 820, 780] * 20)
    assert s is None or s["si"] > 0


def test_stress_level_ordering():
    """Больше ИС → тяжелее уровень."""
    order = ["низкий", "умеренный", "высокий", "перенапряжение"]
    a, b = stress_level(10), stress_level(10000)
    assert order.index(a) < order.index(b)