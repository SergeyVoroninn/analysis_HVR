"""Reference ECGs: import to database and comparison with external program calculation."""
import datetime
import json
import os
import sys
import uuid
import math

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete, ECGRecord
import analysis as hrv
from importer import _import_one

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ETALONS = os.path.join(os.path.dirname(__file__), "etalons.json")


def _load_etalons():
    """Загружает эталоны, гарантированно обрабатывая UTF-8 BOM."""
    with open(ETALONS, "rb") as f:
        content = f.read()
    
    # Если файл начинается с UTF-8 BOM (байты EF BB BF), удаляем их
    if content.startswith(b'\xef\xbb\xbf'):
        content = content[3:]
        
    return json.loads(content.decode('utf-8'))


@pytest.fixture()
def db_with_athlete(tmp_path, request):
    """Creates an empty DB with a recipient athlete and returns (db_path, polar_id, athlete_id)."""
    etalon = request.node.callspec.params.get("etalon")
    polar = etalon["polar_id"]  # Get the actual polar_id from JSON
    
    aid = str(uuid.uuid4())
    db_path = str(tmp_path / "ref.db")
    session = get_session(db_path)
    try:
        session.add(Athlete(
            id=aid, last_name="Reference", first_name="Test", middle_name="",
            gender="M", birth_date=datetime.date(2000, 1, 1),
            height_cm=180, weight_kg=75, resting_hr=60, max_hr=190,
            hrv_rmssd_baseline=50, avg_rr_ms=1000, polar_id=polar))
        session.commit()
    finally:
        session.close()
    return db_path, polar, aid


def _metrics_from_record(rec):
    """Extracts metrics from the DB."""
    return {
        "rmssd": getattr(rec, "rmssd", None),
        "stress_si": getattr(rec, "stress_si", None),
        "mean_hr": getattr(rec, "mean_hr", None),
        "sdnn": getattr(rec, "sdnn", None),
        "tp": getattr(rec, "tp", None),
        "mo_ms": getattr(rec, "mo_ms", None),
    }


def _metrics_from_rr(rr):
    """
    Рассчитывает метрики "на лету", используя ИСКЛЮЧИТЕЛЬНО функции из analysis.py.
    Это гарантирует 100% совпадение логики теста и приложения.
    """
    # 1. Сначала фильтруем артефакты (так же, как это делает приложение перед расчётом)
    seq = hrv.filter_rr(rr)
    if not seq:
        return {
            "mo_ms": None, "stress_si": None, "rmssd": None, 
            "tp": None, "mean_hr": None, "sdnn": None
        }
    
    # 2. Временные метрики и ЧСС (внутри calc_metrics уже есть filter_rr, 
    # но повторный вызов на очищенных данных безопасен и быстр)
    time_metrics = hrv.calc_metrics(seq) or {}
    
    # 3. Метрики стресса (Баевский)
    stress_metrics = hrv.calc_stress(seq) or {}
    
    # 4. Спектральные метрики (PSD)
    _, _, bands = hrv.compute_psd(seq) or (None, None, {})
    
    # Собираем словарь в том же формате, который ожидает тест
    return {
        "mo_ms": stress_metrics.get("mo_ms"),
        "stress_si": stress_metrics.get("si"),  # В analysis.py ключ называется "si"
        "rmssd": time_metrics.get("rmssd"),
        "tp": bands.get("tp") if bands else None,
        "mean_hr": time_metrics.get("mean_hr"),
        "sdnn": time_metrics.get("sdnn"),
    }


@pytest.mark.parametrize("etalon", _load_etalons(),
                         ids=lambda e: os.path.basename(e["file"]))
def test_reference_ecg(etalon, db_with_athlete):
    db_path, polar, aid = db_with_athlete
    path = etalon["file"]
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    assert os.path.exists(path), f"Reference file not found: {path}"

    from athlete_generator import _calc_age
    athletes = [(aid, "Reference", "Test", _calc_age("2000-01-01"), "M", polar)]
    selected = athletes[0]

    # === 1. Import ECG to DB ===
    status, changed_aid = _import_one(db_path, path, athletes, selected, None, interactive=False)
    assert status == "added", f"Import failed: status '{status}'"

    # === 2. Separate metrics: what's in DB and what's calculated on the fly ===
    session = get_session(db_path)
    try:
        rec = session.query(ECGRecord).filter_by(athlete_id=aid).one()
        db_metrics = _metrics_from_record(rec)
    finally:
        session.close()

    with open(path, encoding="utf-8") as f:
        rr = hrv.parse_rr(f.read())
    calc_metrics = _metrics_from_rr(rr)

    ours = {**db_metrics, **calc_metrics}

    # === Extract reference values for visual comparison ===
    exp = etalon["expected"]
    ref_si = exp.get("stress_si", {}).get("value", 0)
    ref_mo = exp.get("mo_ms", {}).get("value", 0)
    ref_rmssd = exp.get("rmssd", {}).get("value", 0)
    ref_tp = exp.get("tp", {}).get("value", 0)
    ref_hr = exp.get("mean_hr", {}).get("value", "N/A")   # <-- Добавлено
    ref_sdnn = exp.get("sdnn", {}).get("value", "N/A")    # <-- Добавлено
    
    # Форматируем HR и SDNN для красивого вывода
    hr_str = f"{ref_hr:>5.1f}" if isinstance(ref_hr, (int, float)) else "  N/A"
    sdnn_str = f"{ref_sdnn:>5.1f}" if isinstance(ref_sdnn, (int, float)) else "  N/A"

    print(f"\n=== OUR STRING (Calculated)   ===")
    print(f"SI={ours.get('stress_si', 0):>6.1f}  Mo={ours.get('mo_ms', 0):>4.0f}  "
          f"RMSSD={ours.get('rmssd', 0):>5.1f}  TP={ours.get('tp', 0):>6.0f}  "
          f"HR={ours.get('mean_hr', 0):>5.1f}  SDNN={ours.get('sdnn', 0):>5.1f}")
    
    print(f"=== REFERENCE STRING (Expected) ===")
    print(f"SI={ref_si:>6.1f}  Mo={ref_mo:>4.0f}  "
          f"RMSSD={ref_rmssd:>5.1f}  TP={ref_tp:>6.0f}  "
          f"HR={hr_str:>5}  SDNN={sdnn_str:>5}")
    print("-" * 78)

    # === 3. Localized comparison with reference ===
    problems = []
    
    # Metrics that are actually saved in the DB
    DB_STORED_FIELDS = {"mean_hr", "rmssd", "sdnn", "stress_si", "tp"}
    
    # Metrics that we DO NOT check (not used in the application)
    SKIP_METRICS = {"nn50", "pnn50"}
    
    def fmt(v):
        return f"{v:.1f}" if v is not None else "None"

    for key, spec in etalon["expected"].items():
        # Skip unused metrics
        if key in SKIP_METRICS:
            continue
            
        value = spec["value"]
        tol = spec.get("tol", 0.10)
        
        db_val = db_metrics.get(key)
        calc_val = calc_metrics.get(key)

        if calc_val is None and db_val is None:
            problems.append(f"[{key}] our program does not calculate and does not store this metric")
            continue
            
        # Check calculation discrepancy (on the fly)
        is_calc_ok = False
        if calc_val is not None:
            diff_calc = abs(calc_val - value)
            is_calc_ok = diff_calc <= abs(value) * tol
            
        # Check discrepancy with DB
        is_db_ok = False
        if db_val is not None:
            diff_db = abs(db_val - value)
            is_db_ok = diff_db <= abs(value) * tol
        elif key not in DB_STORED_FIELDS:
            is_db_ok = True 

        # Form precise error messages
        if not is_calc_ok and not is_db_ok:
            problems.append(
                f"[{key}] CRITICAL DISCREPANCY: reference={value}, "
                f"calculation={fmt(calc_val)}, in DB={fmt(db_val)} "
                f"(tolerance {tol:.0%})"
            )
        elif not is_calc_ok and is_db_ok:
            problems.append(
                f"[{key}] CALCULATION ERROR (DB is correct): reference={value}, "
                f"calculation={fmt(calc_val)}, in DB={fmt(db_val)} "
                f"(calculation discrepancy {diff_calc/abs(value):.1%} > tolerance {tol:.0%})"
            )
        elif is_calc_ok and not is_db_ok:
            problems.append(
                f"[{key}] IMPORT/DB ERROR (calculation is correct!): reference={value}, "
                f"calculation={fmt(calc_val)}, but in DB: {fmt(db_val)} "
                f"(DB discrepancy > tolerance {tol:.0%})"
            )

    assert not problems, "Localized discrepancies with reference:\n" + "\n".join(problems)