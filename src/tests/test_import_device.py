"""
test_import_device.py — этап 2: при импорте запись ЭКГ должна получать
device_id (прибор создаётся по polar_id) и bio_similarity_pct.
"""
from models import get_session, Athlete, ECGRecord, Device
from importer import _import_one


def _write_file(path, serial, dt="2026.09.01 08:00:00"):
    raw = (f"TeamLoggerH10Data\r\n[Header]\r\nversion=1.0\r\n"
           f"datetime={dt}\r\npolar_id={serial}\r\n[ECG]\r\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)


def _seed(db_path, aid, last, first, polar):
    session = get_session(db_path)
    session.add(Athlete(id=aid, last_name=last, first_name=first, polar_id=polar))
    session.commit()
    session.close()


def _athlete_tuple(aid, last, first, polar):
    # формат списка атлетов, как в AthletesPanel: индекс 5 = polar_id
    return (aid, last, first, "", "M", polar)


def test_batch_import_creates_device_and_none_similarity(tmp_path):
    db = str(tmp_path / "db.sqlite")
    f1 = str(tmp_path / "a.teamloggerh10")
    _seed(db, "a1", "Kazakov", "Filipp", "C8219D21")
    _write_file(f1, "C8219D21")

    status, aid = _import_one(
        db, f1, [_athlete_tuple("a1", "Kazakov", "Filipp", "C8219D21")],
        None, None, interactive=False, parent_window=None)
    assert status == "added"
    assert aid == "a1"

    session = get_session(db)
    try:
        rec = session.query(ECGRecord).filter_by(athlete_id="a1").first()
        assert rec is not None
        assert rec.device_id is not None, "device_id должен быть проставлен при импорте"
        dev = session.get(Device, rec.device_id)
        assert dev.serial_number == "C8219D21"
        assert dev.model == "Polar H10"
        # без шаблона корректного сравнения нет → схожесть None
        assert rec.bio_similarity_pct is None
    finally:
        session.close()


def test_two_files_same_device_share_one_row(tmp_path):
    db = str(tmp_path / "db2.sqlite")
    _seed(db, "a1", "Kazakov", "Filipp", "C8219D21")
    f1 = str(tmp_path / "b1.teamloggerh10")
    f2 = str(tmp_path / "b2.teamloggerh10")
    _write_file(f1, "C8219D21", dt="2026.09.01 08:00:00")
    _write_file(f2, "C8219D21", dt="2026.09.02 08:00:00")

    _import_one(db, f1, [_athlete_tuple("a1", "Kazakov", "Filipp", "C8219D21")],
                None, None, interactive=False, parent_window=None)
    _import_one(db, f2, [_athlete_tuple("a1", "Kazakov", "Filipp", "C8219D21")],
                None, None, interactive=False, parent_window=None)

    session = get_session(db)
    try:
        assert session.query(ECGRecord).count() == 2
        assert session.query(Device).count() == 1, "один прибор не должен дублироваться в таблице device"
    finally:
        session.close()