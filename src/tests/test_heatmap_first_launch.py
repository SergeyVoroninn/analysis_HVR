"""
Тест-регрессия: тепловые карты (yearmap/weekmap) НЕ должны быть пустыми
при первом запуске, если в БД есть данные атлета.

Воспроизводит сценарий «первый запуск»:
  1. БД заполнена записями ЭКГ для атлета;
  2. на heatmap устанавливается атлет (сеттер → _load_data);
  3. проверяется, что date_map/block_map заполнены и ячейки перекрашены.

Раньше загрузка шла асинхронно через отдельный поток + after(0,...), из-за чего
при первом запуске карты могли показаться пустыми (гонка потоков / сброс по seq).
Теперь загрузка синхронная — карты обязаны заполниться сразу.
"""
import datetime
import os
import sys
import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete, ECGRecord  # noqa: E402
from yearmap import YearHeatmap  # noqa: E402
from weekmap import WeekHeatmap  # noqa: E402


def _make_db_with_records():
    """Создаёт in-memory БД с одним атлетом и записями ЭКГ. Возвращает db_path.

    ВАЖНО: get_session(":memory:") отдаёт единый персистентный in-memory engine,
    поэтому БД создаётся один раз через session-scoped фикстуру `db_path`.
    """
    session = get_session(":memory:")
    session.query(ECGRecord).delete()
    session.query(Athlete).delete()
    session.add(Athlete(id="a1", last_name="Тест", first_name="Атлет"))
    session.add_all([
        ECGRecord(athlete_id="a1", recorded_at="2026-08-08 08:47:04"),
        ECGRecord(athlete_id="a1", recorded_at="2026-08-08 09:16:48"),
        ECGRecord(athlete_id="a1", recorded_at="2026-08-10 08:33:14"),
        ECGRecord(athlete_id="a1", recorded_at="2026-08-10 11:00:00"),
        ECGRecord(athlete_id="a1", recorded_at="2026-08-11 08:48:07"),
    ])
    session.commit()
    session.close()
    return ":memory:"


@pytest.fixture(scope="session")
def db_path():
    return _make_db_with_records()


@pytest.fixture
def yearmap_filled(db_path):
    ym = YearHeatmap.__new__(YearHeatmap)
    ym.db_path = db_path
    ym._athlete_id = None
    ym._year = 2026
    ym._year_start = datetime.date(2025, 12, 29)  # понедельник, 1 января 2026
    ym._week = None
    ym._date_map = {}
    ym._cells = [object() for _ in range(53 * 7)]
    ym._colors = [None] * (53 * 7)
    ym._month_labels = []
    ym._redraw_cells = lambda: None  # интерфейсная часть нам не нужна
    return ym


@pytest.fixture
def weekmap_filled(db_path):
    wm = WeekHeatmap.__new__(WeekHeatmap)
    wm.db_path = db_path
    wm._athlete_id = None
    wm._week_start = datetime.date(2026, 8, 3)
    wm._block_map = {}
    wm._redraw = lambda: None
    return wm


# yearmap: при установке атлета _load_data синхронно заполняет date_map
def test_yearmap_data_loaded_sync_after_setting_athlete(yearmap_filled):
    ym = yearmap_filled
    ym._athlete_id = "a1"
    ym._load_data()
    # Должны быть найдены даты из БД
    assert "2026-08-08" in ym._date_map, "yearmap не увидела записи от 08.08"
    assert "2026-08-10" in ym._date_map, "yearmap не увидела записи от 10.08"
    assert ym._date_map["2026-08-08"]["count"] == 2
    assert ym._date_map["2026-08-10"]["count"] == 2


def test_yearmap_empty_when_no_athlete(yearmap_filled):
    ym = yearmap_filled
    ym._athlete_id = None
    ym._load_data()
    assert ym._date_map == {}, "без атлета карта должна остаться пустой"


# weekmap: та же логика
def test_weekmap_data_loaded_sync_after_setting_athlete(weekmap_filled):
    wm = weekmap_filled
    wm._athlete_id = "a1"
    wm._load_data()
    # 08.08 — день 5 (воскресенье 09.08? нет): 08.08.2026 это суббота
    # Проверяем наличие ключей блоков: (дата, hour//3)
    assert any(k[0] == "2026-08-10" for k in wm._block_map), "weekmap не увидела 10.08"
    assert any(k[0] == "2026-08-11" for k in wm._block_map), "weekmap не увидела 11.08"


def test_weekmap_empty_when_no_athlete(weekmap_filled):
    wm = weekmap_filled
    wm._athlete_id = None
    wm._load_data()
    assert wm._block_map == {}, "без атлета недельная карта должна остаться пустой"


# Регрессия первого запуска: установка атлета + refresh не оставляет карты пустыми.
def test_first_launch_heatmap_not_empty_after_athlete_set(gui_root, db_path):
    """Имитация первого запуска: атлета нет, потом выбирается первый → карты заполняются."""
    from heatmap import Heatmap

    hm = Heatmap(gui_root, db_path=db_path)
    hm.pack()
    gui_root.update()

    # На первом запуске сначала атлета нет (карты пустые)...
    hm.athlete = None
    gui_root.update()

    # ...затем вызывается sync_athlete первого атлета
    hm.athlete = "a1"
    gui_root.update()

    # refresh() в app.py вызывается после restore_state
    hm.refresh()
    gui_root.update()

    # Карты должны быть заполнены данными
    assert "2026-08-08" in hm.year_map._date_map, \
        "годовая карта осталась пустой после первого запуска"
    assert any(k[0] == "2026-08-08" for k in hm.week_map._block_map), \
        "недельная карта осталась пустой после первого запуска"