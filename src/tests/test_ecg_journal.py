"""
test_ecg_journal.py — этап 3: единый журнал ЭКГ (ECGJournal) показывает
записи с прибором и процентом схожести, подсвечивает низкую схожесть,
поддерживает сортировку по заголовкам и фильтрацию по интервалу.
"""
import datetime

from models import get_session, Athlete, ECGRecord, Device
from dialogs import ECGJournal


def _seed(db_path):
    session = get_session(db_path)
    athlete = Athlete(id="a1", last_name="Kazakov", first_name="Filipp",
                      polar_id="C8219D21")
    dev = Device(serial_number="C8219D21")
    session.add_all([athlete, dev])
    session.flush()

    r_low = ECGRecord(athlete_id="a1", recorded_at="2026-08-20 09:15:18",
                      device_id=dev.id, bio_similarity_pct=10.0, status="ok")
    r_high = ECGRecord(athlete_id="a1", recorded_at="2026-08-21 10:00:00",
                       device_id=dev.id, bio_similarity_pct=80.0, status="crit")
    session.add_all([r_low, r_high])
    session.commit()
    session.close()


def test_journal_lists_records_with_device_and_highlight(gui_root, tmp_path):
    db = str(tmp_path / "j.sqlite")
    _seed(db)

    journal = ECGJournal(gui_root, athlete_id="a1", db_path=db,
                         title="Тест журнала")
    gui_root.update()

    items = journal.tree.get_children()
    assert len(items) == 2, f"ожидалось 2 записи, получено {len(items)}"

    # у всех строк есть id в tags; у низкой схожести должен быть тег 'crit'
    has_crit = False
    has_device = False
    for item in items:
        tags = journal.tree.item(item, "tags")
        values = journal.tree.item(item, "values")
        if "crit" in tags:
            has_crit = True
        if "C8219D21" in values[1]:
            has_device = True
    assert has_crit, "запись со схожестью <30% должна быть помечена 'crit'"
    assert has_device, "в колонке прибора должен быть серийный номер"

    journal.destroy()


def test_journal_interval_mode_filters_by_date(gui_root, tmp_path):
    db = str(tmp_path / "j2.sqlite")
    _seed(db)

    dt_from = datetime.datetime(2026, 8, 20, 0, 0, 0)
    dt_to = datetime.datetime(2026, 8, 21, 0, 0, 0)
    journal = ECGJournal(gui_root, athlete_id="a1", db_path=db,
                         date_from=dt_from, date_to=dt_to,
                         title="За интервал")
    gui_root.update()
    assert len(journal.tree.get_children()) == 1, "в интервале должна быть только запись 20.08"
    journal.destroy()


def test_journal_sort_by_header_switches_order(gui_root, tmp_path):
    db = str(tmp_path / "j3.sqlite")
    _seed(db)

    journal = ECGJournal(gui_root, athlete_id="a1", db_path=db,
                         date_from=datetime.datetime(2026, 8, 18),
                         date_to=datetime.datetime(2026, 8, 22),
                         title="Сортировка")
    gui_root.update()

    # по умолчанию интервал сортируется по Время ASC (20.08 раньше 21.08)
    first_asc = journal.tree.item(journal.tree.get_children()[0], "values")[2]

    journal._sort_by("Время")  # повторный клик -> DESC
    gui_root.update()
    first_desc = journal.tree.item(journal.tree.get_children()[0], "values")[2]
    assert first_asc != first_desc, "смена направления сортировки должна изменить порядок"

    journal.destroy()