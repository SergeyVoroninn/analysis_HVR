from models import get_session, Athlete, ECGRecord


def test_crud_and_cascade(tmp_path):
    db = str(tmp_path / "test.db")
    s = get_session(db)

    a = Athlete(id="a1", last_name="Тест", first_name="И", polar_id="P1")
    s.add(a)
    s.commit()

    s.add(ECGRecord(athlete_id="a1", recorded_at="2026-01-01 10:00:00", sdnn=50))
    s.commit()
    assert s.query(ECGRecord).count() == 1

    s.delete(a)
    s.commit()
    assert s.query(ECGRecord).count() == 0   # каскадное удаление
    s.close()