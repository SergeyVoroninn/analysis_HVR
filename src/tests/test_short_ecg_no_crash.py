"""
test_short_ecg_no_crash.py — устойчивость фильтрации к коротким записям ЭКГ.

Импортированные короткие записи (мало сэмплов) раньше валили
scipy.signal.filtfilt -> ValueError ("input ... must be greater than padlen").
Гарантируем, что фильтрация и ранжирование не бросают исключений на таких записях.
"""
import os
import sys

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)

from ecg_biometrics import _parse_and_clean_ecg, rank_athletes_for_raw, bio_failure_reason  # noqa: E402
from analysis import clean_ecg, parse_rr  # noqa: E402

SHORT_RAW = ("TeamLoggerH10Data\n[Header]\npolar_id=C8219D21\n[ECG]\n"
             "1:" + ",".join(str(x) for x in range(5)) + "\n")


def test_parse_and_clean_short_ecg_does_not_raise():
    sig = _parse_and_clean_ecg(SHORT_RAW)
    assert len(sig) >= 0


def test_clean_ecg_short_does_not_raise():
    import numpy as np
    sig = clean_ecg(np.arange(5, dtype=float), 130.0)
    assert len(sig) == 5


def test_parse_rr_short_file_does_not_raise():
    # [ECG] короткий -> fallback-детекция RR не должна падать
    rr = parse_rr(SHORT_RAW)
    assert isinstance(rr, list)


def test_rank_athletes_does_not_raise_on_short(tmp_path):
    db = str(tmp_path / "x.db")
    # БД без шаблонов — ранжирование вернёт [] и не должно бросать исключений
    result = rank_athletes_for_raw(db, SHORT_RAW, current_athlete_id=None)
    assert isinstance(result, list)


def test_bio_failure_reason_distinguishes_no_ecg_and_bad_signal():
    assert "нет ЭКГ" in bio_failure_reason("H\n[Header]\n[RR]\n500,520\n")
    assert "R-зубцы" in bio_failure_reason("H\n[ECG]\n1:10,20,30,40\n")
    assert "без данных" in bio_failure_reason("H\n[ECG]\n1:\n")
    assert "нет данны" in bio_failure_reason("")