"""
test_reference_ecg.py — регрессионный тест расчёта метрик HRV по эталонным ЭКГ.

Задача: подсветить, когда в алгоритм расчёта метрик (analysis.py) внесены изменения.

Строгие допуски + golden-значения:
  - Набор эталонных файлов читается из etalons.json (там же лежат справочные
    значения Омега.Диагностика — выводятся для контекста, но НЕ участвуют в
    жёсткой проверке).
  - Тест считает метрики текущим алгоритмом и сверяет их со строгим допуском
    с сохранёнными golden-значениями (эталон = наши собственные значения).
  - Любое изменение в алгоритме/настройках анализа меняет числа -> тест падает
    с диффом, указывая на изменённые метрики.

Поведение golden:
  - Если reference_golden.json нет или установлена UPDATE_GOLDEN=1 — тест
    пересчитывает и сохраняет актуальные значения (первый прогон/сознательная
    пересборка).
  - Иначе сверяет с сохранёнными. Расхождение > STRICT_REL_TOL -> FAIL.

Проверка фиксирует 6 метрик (все через analysis.py на лету):
  rmssd, sdnn, mean_hr, stress_si, mo_ms, tp.
"""
import hashlib
import json
import os
import sys
import uuid

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete, ECGRecord  # noqa: E402
import analysis as hrv                            # noqa: E402
from importer import _import_one                   # noqa: E402

REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "ekg_reference")
ETALONS = os.path.join(REFERENCE_DIR, "etalons.json")
GOLDEN = os.path.join(REFERENCE_DIR, "reference_golden.json")

# Строгий относительный допуск сверки с golden (0.01%).
# Достаточно мал, чтобы ловить любые содержательные изменения алгоритма,
# и достаточно велик для стабильности чисел с плавающей точкой между прогонами.
STRICT_REL_TOL = 1e-4

METRICS = ["rmssd", "mean_hr", "stress_si", "mo_ms", "tp"]


def _load_json(path):
    with open(path, "rb") as f:
        content = f.read()
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    return json.loads(content.decode("utf-8"))


def _file_digest(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_etalons():
    """Загружает эталоны, гарантированно обрабатывая UTF-8 BOM."""
    return _load_json(ETALONS)


@ pytest.fixture()
def db_with_athlete(tmp_path, request):
    """Creates an empty DB with a recipient athlete and returns (db_path, polar_id, athlete_id)."""
    etalon = request.node.callspec.params.get("etalon")
    polar = etalon["polar_id"]

    aid = str(uuid.uuid4())
    db_path = str(tmp_path / "ref.db")
    session = get_session(db_path)
    try:
        session.add(Athlete(
            id=aid, last_name="Reference", first_name="Test", middle_name="",
            gender="M", birth_date=None, height_cm=None, weight_kg=None,
            resting_hr=None, max_hr=None, hrv_rmssd_baseline=None,
            avg_rr_ms=None, polar_id=polar))
        session.commit()
    finally:
        session.close()
    return db_path, polar, aid


def _metrics_from_record(rec):
    """Извлекает метрики из БД."""
    return {
        "rmssd": getattr(rec, "rmssd", None),
        "stress_si": getattr(rec, "stress_si", None),
        "mean_hr": getattr(rec, "mean_hr", None),
        "tp": getattr(rec, "tp", None),
        "mo_ms": getattr(rec, "mo_ms", None),
    }


def _metrics_from_rr(rr):
    """Считает метрики на лету ИСКЛЮЧИТЕЛЬНО через analysis.py — совпадает с приложением."""
    seq = hrv.filter_rr(rr)
    if not seq:
        return {m: None for m in METRICS}

    time_metrics = hrv.calc_metrics(seq) or {}
    stress_metrics = hrv.calc_stress(seq) or {}
    _, _, bands = hrv.compute_psd(seq) or (None, None, {})

    return {
        "rmssd": time_metrics.get("rmssd"),
        "mean_hr": time_metrics.get("mean_hr"),
        "stress_si": stress_metrics.get("si"),
        "mo_ms": stress_metrics.get("mo_ms"),
        "tp": bands.get("tp") if bands else None,
    }


def _compute_ours(db_path, aid, etalon_path, tmp_path):
    """Импортирует запись, считает метрики анализом и возвращает (ours, rec, rr)."""
    from athlete_generator import _calc_age
    athletes = [(aid, "Reference", "Test", _calc_age("2000-01-01"), "M", None)]
    selected = athletes[0]

    status, changed_aid = _import_one(db_path, etalon_path, athletes, selected,
                                      None, interactive=False)
    assert status == "added", f"Import failed: status '{status}'"

    session = get_session(db_path)
    try:
        rec = session.query(ECGRecord).filter_by(athlete_id=aid).one()
        db_metrics = _metrics_from_record(rec)
    finally:
        session.close()

    with open(etalon_path, encoding="utf-8") as f:
        rr = hrv.parse_rr(f.read())
    calc_metrics = _metrics_from_rr(rr)

    return {**db_metrics, **calc_metrics}, rec, rr


def _dataset_key(etalon_path):
    """Контрольный ключ эталона (md5 файла) — ловит подмену данных."""
    return _file_digest(etalon_path)


@pytest.mark.parametrize("etalon", _load_etalons(),
                         ids=lambda e: os.path.basename(e["file"]))
def test_reference_ecg(etalon, db_with_athlete, tmp_path):
    db_path, polar, aid = db_with_athlete
    rel_file = etalon["file"]
    path = rel_file if os.path.isabs(rel_file) else os.path.join(REFERENCE_DIR, rel_file)
    assert os.path.exists(path), f"Reference file not found: {path}"
    name = os.path.basename(path)

    ours, rec, rr = _compute_ours(db_path, aid, path, tmp_path)
    digest = _dataset_key(path)

    # Справочные значения Омега.Диагностика — только для контекста, не для проверки.
    exp = etalon.get("expected", {})
    print(f"\n=== {name} ===")
    for m in METRICS:
        ref = exp.get(m, {}).get("value") if isinstance(exp.get(m), dict) else None
        print(f"  {m:>9}: ours={ours.get(m)}  (omega_ref={ref})")

    if os.environ.get("UPDATE_GOLDEN") == "1" or not os.path.exists(GOLDEN):
        golden = _load_or_init_golden()
        golden["results"][name] = {m: ours.get(m) for m in METRICS}
        golden["dataset_key"][name] = digest
        _write_golden(golden)
        pytest.skip(f"UPDATE_GOLDEN/нет golden: записаны значения для {name}")

    golden = _load_json(GOLDEN)
    assert name in golden.get("results", {}), (
        f"Нет golden-значений для {name}. Пересобери: UPDATE_GOLDEN=1 pytest ...")

    if golden["dataset_key"].get(name) != digest:
        pytest.fail(
            f"Изменился содержимое эталонного файла {name}. "
            f"Обнови golden: UPDATE_GOLDEN=1 pytest ...")

    expected = golden["results"][name]
    problems = []
    for m in METRICS:
        cur = ours.get(m)
        ref = expected.get(m)
        if cur is None or ref is None:
            if cur != ref:
                problems.append(f"[{m}] {"None" if cur is None else "%.6g" % cur} "
                                f"-> {"None" if ref is None else "%.6g" % ref}")
            continue
        diff = abs(cur - ref)
        denom = abs(ref) if ref != 0 else 1.0
        if diff > STRICT_REL_TOL * denom:
            problems.append(f"[{m}] {cur:.6g} -> {ref:.6g} (отклонение "
                            f"{diff / denom:.2e} > {STRICT_REL_TOL:.0e})")

    assert not problems, (
        f"Метрики {name} ИЗМЕНИЛИСЬ относительно golden "
        f"(reference_golden.json). Похоже, в алгоритм analysis.py внесены "
        f"правки.\n" + "\n".join(problems))


def _load_or_init_golden():
    if os.path.exists(GOLDEN):
        try:
            return _load_json(GOLDEN)
        except Exception:
            pass
    return {"dataset_key": {}, "results": {}, "metric_notes": METRICS}


def _write_golden(golden):
    with open(GOLDEN, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2)