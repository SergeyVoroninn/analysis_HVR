"""
test_import_similarity.py — импорт при биометрическом несовпадении.

Проверяет, что при status=SUSPICIOUS и наличии подходящих кандидатов импортёр
открывает единое окно SimilarityDialog и по результату выбора переназначает
запись нужному атлету, сохраняя % схожести. Регрессионная защита ветки
«слабое совпадение при импорте» (раньше здесь была ошибка: self.db_path
в модульной функции -> NameError).
"""
import os
import sys

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)

from models import get_session, Athlete, ECGRecord  # noqa: E402
import importer as imp  # noqa: E402

# реальный файл ЭКГ для чтения raw
REF_FILE = os.path.join(SRC, "tests", "ekg_reference",
                        "C8219D21_2026_08_15_09_07_07_teamloggerh10.teamloggerh10")


class _Ath:
    def __init__(self, aid, last, first):
        self.id = aid
        self.last_name = last
        self.first_name = first


def _candidate(a, prob):
    return {"athlete": a, "distance": 0.05, "probability": prob,
            "records_used": 20, "is_current": False, "is_relative": False}


def test_import_suspicious_redirects_to_similarity(monkeypatch, tmp_path):
    db = str(tmp_path / "imp.db")
    cur_aid = "cur-1"
    other_aid = "other-2"

    session = get_session(db)
    session.add_all([Athlete(id=cur_aid, last_name="Текущий", first_name="Атлет"),
                     Athlete(id=other_aid, last_name="Лучший", first_name="Атлет")])
    session.commit()
    session.close()

    # Мокаем биометрию, чтобы запись получила status=SUSPICIOUS и кандидатов
    monkeypatch.setattr(imp, "check_ownership_with_saved_template",
                        lambda *a, **k: ("SUSPICIOUS", 0.9, 0.05))
    monkeypatch.setattr(imp, "rank_athletes_for_raw",
                        lambda *a, **k: [_candidate(_Ath(other_aid, "Лучший", "Атлет"), 0.85),
                                         _candidate(_Ath(cur_aid, "Текущий", "Атлет"), 0.05)])
    monkeypatch.setattr(imp, "_are_relatives_by_name", lambda *a, **k: False)

    # Мокаем единое окно сходства: запоминаем вызов и возвращаем выбор "другого" атлета
    captured = {}

    class FakeSimilarityDialog:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def modal_loop(self):
            return {"athlete_id": other_aid, "probability": 0.85}

    monkeypatch.setattr(imp, "SimilarityDialog", FakeSimilarityDialog)

    athletes = [(cur_aid, "Текущий", "Атлет", 25, "M", "C8219D21")]
    status, changed = imp._import_one(
        db, REF_FILE, athletes, athletes[0], None,
        interactive=True, parent_window=object())
    assert status == "added", f"ожидался 'added', получено '{status}'"
    assert changed == other_aid, "запись должна быть переназначена выбранному атлету"

    # Окно открыто и получило raw-данные + текущего атлета
    assert captured["args"][1] == db, "в окно должен передаваться путь к БД"
    assert captured["kwargs"].get("current_athlete_id") == cur_aid
    assert isinstance(captured["args"][2], str) and "[ECG]" in captured["args"][2], \
        "в окно должны передаваться raw-данные записи"

    # Запись сохранена у выбранного атлета со схожестью = выбранная вероятность
    session = get_session(db)
    try:
        rec = session.query(ECGRecord).filter_by(athlete_id=other_aid).one()
        assert rec.bio_similarity_pct is not None
        assert rec.bio_similarity_pct == pytest.approx(0.85 * 100, abs=0.01)
    finally:
        session.close()


def test_import_suspicious_cancel_returns_cancelled(monkeypatch, tmp_path):
    db = str(tmp_path / "imp2.db")
    cur_aid = "cur-1"

    session = get_session(db)
    session.add(Athlete(id=cur_aid, last_name="Текущий", first_name="Атлет"))
    session.commit()
    session.close()

    monkeypatch.setattr(imp, "check_ownership_with_saved_template",
                        lambda *a, **k: ("SUSPICIOUS", 0.9, 0.05))
    monkeypatch.setattr(imp, "rank_athletes_for_raw",
                        lambda *a, **k: [_candidate(_Ath("x-1", "X", "Y"), 0.9)])
    monkeypatch.setattr(imp, "_are_relatives_by_name", lambda *a, **k: False)

    class CancelDialog:
        def __init__(self, *args, **kwargs):
            pass

        def modal_loop(self):
            return None  # отмена/закрытие без выбора

    monkeypatch.setattr(imp, "SimilarityDialog", CancelDialog)

    athletes = [(cur_aid, "Текущий", "Атлет", 25, "M", "C8219D21")]
    status, changed = imp._import_one(
        db, REF_FILE, athletes, athletes[0], None,
        interactive=True, parent_window=object())
    assert status == "cancelled", f"при отмене ожидался 'cancelled', получено '{status}'"