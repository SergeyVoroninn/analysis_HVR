"""Эталонные ЭКГ: импорт в базу и сверка с расчётом внешней программы."""
import json
import os
import sys
import uuid

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
    with open(ETALONS, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def db_with_athlete(tmp_path):
    """Создаёт пустую БД со спортсменом-приёмником и возвращает (db_path, polar_id, athlete_id)."""
    polar = "C821EB2E"
    aid = str(uuid.uuid4())
    db_path = str(tmp_path / "ref.db")
    session = get_session(db_path)
    try:
        session.add(Athlete(
            id=aid, last_name="Эталон", first_name="Тест", middle_name="",
            gender="M", birth_date="2000-01-01",
            height_cm=180, weight_kg=75, resting_hr=60, max_hr=190,
            hrv_rmssd_baseline=50, avg_rr_ms=1000, polar_id=polar))
        session.commit()
    finally:
        session.close()
    return db_path, polar, aid


def _metrics_from_record(rec):
    return {
        "rmssd": rec.rmssd,
        "stress_si": rec.stress_si,
        "mean_hr": rec.mean_hr,
        "sdnn": rec.sdnn,
    }


def _metrics_from_rr(rr):
    seq = hrv.filter_rr(rr)
    s = hrv.calc_stress(rr) or {}
    diffs = [abs(b - a) for a, b in zip(seq, seq[1:])]
    nn50 = sum(1 for d in diffs if d > 50)
    pnn50 = 100.0 * nn50 / len(diffs) if diffs else 0.0
    _, _, bands = hrv.compute_psd(seq)
    return {
        "mo_ms": s.get("mo_ms"),
        "nn50": nn50,
        "pnn50": pnn50,
        "tp": bands.get("tp"),
    }


@pytest.mark.parametrize("etalon", _load_etalons(),
                         ids=lambda e: os.path.basename(e["file"]))
def test_reference_ecg(etalon, db_with_athlete):
    db_path, polar, aid = db_with_athlete
    path = etalon["file"]
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    assert os.path.exists(path), f"Эталонный файл не найден: {path}"

    # --- список спортсменов в формате (id, last, first, age, gender, polar_id) ---
    from athlete_generator import _calc_age
    athletes = [(aid, "Эталон", "Тест", _calc_age("2000-01-01"), "M", polar)]
    selected = athletes[0]

    # === 1. Импорт ЭКГ в базу ===
    status, changed_aid = _import_one(db_path, path, athletes, selected, None, interactive=False)
    assert status == "added", f"Импорт не выполнен: статус '{status}'"

    # === 2. Наши метрики: БД + на лету из RR ===
    session = get_session(db_path)
    try:
        rec = session.query(ECGRecord).filter_by(athlete_id=aid).one()
        ours = _metrics_from_record(rec)
    finally:
        session.close()

    with open(path, encoding="utf-8") as f:
        rr = hrv.parse_rr(f.read())
    ours.update(_metrics_from_rr(rr))

    # === Наша строка в формате Омеги ===
    print(f"\n=== НАША СТРОКА (формат Омеги) ===")
    print(f"ИН={ours['stress_si']:.1f}  Мо={ours['mo_ms']:.0f}  "
          f"RMSSD={ours['rmssd']:.1f}  NN50={ours['nn50']}  "
          f"pNN50={ours['pnn50']:.1f}  TP={ours['tp']:.0f}  "
          f"ЧСС={ours['mean_hr']:.0f}")

    # === 3. Сверка с эталоном ===
    problems = []
    for key, spec in etalon["expected"].items():
        value, tol = spec["value"], spec.get("tol", 0.10)
        got = ours.get(key)
        if got is None:
            problems.append(f"{key}: наша программа не вычисляет эту метрику")
            continue
        diff = abs(got - value)
        if diff > abs(value) * tol:
            problems.append(
                f"{key}: эталон {value}, получено {got:.1f} "
                f"(расхождение {diff / abs(value):.1%} > допуска {tol:.0%})")

    assert not problems, "Расхождение с эталоном:\n" + "\n".join(problems)