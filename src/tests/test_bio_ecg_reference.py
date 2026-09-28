# -*- coding: utf-8 -*-
"""
test_bio_ecg_reference.py — регрессионный тест модуля определения атлета по ЭКГ.

Идея (гипотеза пользователя):
  Есть атлет, "выбранный эталоном" (тот, у кого больше всего записей). Из его
  записей строится биометрический шаблон (template/ в bio_ecg_reference).
  Берётся по одной записи каждого атлета (probes/) и сравнивается с шаблоном.
  Запись ЭТАЛОНА должна давать НАИБОЛЬШЕЕ совпадение (минимальное расстояние).

  Результаты сравнения сохраняются в results_golden.json. Если текущие
  результаты отличаются от сохранённых — значит изменились настройки алгоритма
  (класс ECGConfig) или сам алгоритм; тест это подсвечивает.

Поведение golden-файла:
  - Если results_golden.json нет, тест создаёт его и проходит (первый запуск).
  - Иначе сверяет текущие результаты с сохранёнными и падает при расхождении.
  - Чтобы сознательно пересобрать эталон:  UPDATE_GOLDEN=1 pytest ...
"""
import json
import os
import sys
import uuid

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete, ECGRecord, ECGRaw  # noqa: E402
import ecg_biometrics as bio                              # noqa: E402

REF_DIR = os.path.join(os.path.dirname(__file__), "bio_ecg_reference")
MANIFEST = os.path.join(REF_DIR, "manifest.json")
GOLDEN = os.path.join(REF_DIR, "results_golden.json")

# Относительный допуск при сравнении с golden-результатами.
# DTW-расстояния детерминированы, но допускаем погрешность плавающей точки.
DISTANCE_TOLERANCE = 1e-6
PROBABILITY_TOLERANCE = 1e-6

DISTANCE_TYPE = "distance"  # метрика "наибольшего совпадения" = минимальное расстояние


def _load_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return json.loads(raw.decode("utf-8"))


def _template_order(manifest):
    """Имя файла шаблона и его дедуплицированный хэш-ключ."""
    return [r["file"] for r in manifest["template"]["records"]]


def _build_session_with_template(tmp_path, manifest, etalon):
    """Создаёт временную БД: атлет-эталон + его записи из template/ (для шаблона)."""
    db_path = str(tmp_path / "bio.db")
    aid = str(uuid.uuid4())
    session = get_session(db_path)
    try:
        session.add(Athlete(
            id=aid, last_name=etalon, first_name=etalon, middle_name="",
            gender="M", birth_date=None, height_cm=None, weight_kg=None,
            resting_hr=None, max_hr=None, hrv_rmssd_baseline=None,
            avg_rr_ms=None, polar_id="TEST_REF"))
        session.commit()

        files = _template_order(manifest)
        for i, rel in enumerate(files):
            path = os.path.join(REF_DIR, rel)
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            rec = ECGRecord(athlete_id=aid, recorded_at=f"2026-01-01 {i:02d}:00:00",
                            duration_seconds=60.0)
            session.add(rec)
            session.flush()
            session.add(ECGRaw(record_id=rec.id, raw_data=raw))
        session.commit()
    finally:
        session.close()
    return db_path, aid


def _score_probes(db_path, aid, manifest):
    """Сравнивает каждую пробу с шаблоном через реальные функции модуля."""
    results = {}
    ok, msg = bio.create_and_save_template(db_path, aid)
    assert ok, f"Не удалось построить шаблон: {msg}"
    assert msg  # для информативности

    for athlete, info in manifest["probes"].items():
        probe_path = os.path.join(REF_DIR, info["file"])
        status, distance, probability = bio.check_ownership_with_saved_template(
            db_path, aid, probe_path)
        results[athlete] = {
            "distance": float(distance),
            "probability": float(probability),
            "status": status,
        }
    return results


def _dataset_key(manifest):
    """Контрольный ключ набора: эталон + хэши шаблона + пробы. Ловит подмену данных."""
    tpl = [r["content_hash"] for r in manifest["template"]["records"]]
    probes = {athlete: info["content_hash"]
              for athlete, info in manifest["probes"].items()}
    return {
        "etalon_athlete": manifest["etalon_athlete"],
        "template_hashes": sorted(tpl),
        "probe_hashes": probes,
    }


def test_etalon_matches_best(tmp_path):
    """Запись эталона должна давать минимальное (наилучшее) расстояние до шаблона."""
    manifest = _load_json(MANIFEST)
    etalon = manifest["etalon_athlete"]
    db_path, aid = _build_session_with_template(tmp_path, manifest, etalon)

    results = _score_probes(db_path, aid, manifest)

    ranking = sorted(results.items(), key=lambda kv: kv[1][DISTANCE_TYPE])
    best_athlete = ranking[0][0]

    print("\n=== Совпадение каждой записи с шаблоном эталона ===")
    for athlete, r in sorted(results.items()):
        print(f"  {athlete:12} distance={r['distance']:.6f}  "
              f"probability={r['probability']:.6f}  status={r['status']}")

    assert best_athlete == etalon, (
        f"Запись эталона '{etalon}' НЕ дала наибольшее совпадение. "
        f"Лучшее совпадение у '{best_athlete}'. Проверь данные или пороги.")

    # Запись эталона должна быть реальным совпадением (не BAD_SIGNAL / ERROR)
    etalon_status = results[etalon]["status"]
    assert etalon_status == "MATCH", (
        f"Запись эталона дала статус '{etalon_status}' вместо 'MATCH'.")


def test_results_unchanged_since_golden(tmp_path):
    """Результаты сравнения не должны меняться, если не трогали настройки/алгоритм."""
    manifest = _load_json(MANIFEST)
    etalon = manifest["etalon_athlete"]
    db_path, aid = _build_session_with_template(tmp_path, manifest, etalon)
    current = _score_probes(db_path, aid, manifest)

    key = _dataset_key(manifest)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        with open(GOLDEN, "w", encoding="utf-8") as f:
            json.dump({"dataset_key": key, "results": current, "metric": DISTANCE_TYPE},
                      f, ensure_ascii=False, indent=2)
        pytest.skip("UPDATE_GOLDEN=1: golden-результаты перезаписаны")

    assert os.path.exists(GOLDEN), (
        f"Первый запуск: golden-файл {GOLDEN} не найден. "
        f"Запусти один раз, чтобы сохранить эталонные результаты.")

    golden = _load_json(GOLDEN)

    if golden.get("dataset_key") != key:
        pytest.fail(
            "Изменился эталонный набор данных (шаблон/пробы). "
            "Пересобери bio_ecg_reference (build_bio_ecg_reference.py) "
            "и обнови golden: UPDATE_GOLDEN=1.")

    expected = golden["results"]
    problems = []
    for athlete, cur in current.items():
        exp = expected.get(athlete)
        if exp is None:
            problems.append(f"[{athlete}] отсутствует в golden-файле")
            continue
        d_diff = abs(cur["distance"] - exp["distance"])
        p_diff = abs(cur["probability"] - exp["probability"])
        if d_diff > DISTANCE_TOLERANCE or p_diff > PROBABILITY_TOLERANCE:
            problems.append(
                f"[{athlete}] distance {cur['distance']:.6f} -> {exp['distance']:.6f} "
                f"(Δ{d_diff:.2e}), probability {cur['probability']:.6f} -> "
                f"{exp['probability']:.6f} (Δ{p_diff:.2e})")

    assert not problems, (
        "Результаты сравнения атлетов с шаблоном ИЗМЕНИЛИСЬ по сравнению с "
        "results_golden.json. Похоже, изменились настройки (класс ECGConfig в "
        "ecg_biometrics.py) или в алгоритм внесены правки.\n"
        + "\n".join(problems))