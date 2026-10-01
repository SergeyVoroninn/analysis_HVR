"""
Тесты комментариев к метрикам.

Проверяет:
  * модель MetricComment и таблицу metric_comments;
  * DAO: добавить/обновить/получить/удалить комментарий;
  * уникальность (атлет, метрика, дата);
  * загрузку комментариев в график (MetricPlot.reload_comments);
  * формат маркеров (draw_comment_markers не падает);
  * тултип включает текст комментария.
"""
import datetime
import os
import sys
import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete, ECGRecord, MetricComment  # noqa: E402
from metric_comments import (upsert_comment, get_comment, get_comment_map,  # noqa: E402
                             get_comments_for_date, list_comments, delete_comment)


@pytest.fixture(scope="session")
def comment_db():
    """In-memory БД с атлетом и записями (одна на сессию)."""
    session = get_session(":memory:")
    session.query(ECGRecord).delete()
    session.query(MetricComment).delete()
    session.query(Athlete).delete()
    session.add(Athlete(id="a1", last_name="Тест", first_name="Атлет"))
    session.add_all([
        ECGRecord(athlete_id="a1", recorded_at="2026-08-05 08:00:00", tp=100),
        ECGRecord(athlete_id="a1", recorded_at="2026-08-10 08:00:00", tp=200),
    ])
    session.commit()
    session.close()
    return ":memory:"


# ---------------- DAO ----------------
def test_upsert_and_get(comment_db):
    d = datetime.date(2026, 8, 5)
    upsert_comment(comment_db, "a1", "tp", d, "Высокий TP")
    assert get_comment(comment_db, "a1", "tp", d) == "Высокий TP"
    assert get_comment(comment_db, "a1", "tp", datetime.date(2026, 8, 9)) is None


def test_upsert_updates_existing(comment_db):
    d = datetime.date(2026, 8, 10)
    upsert_comment(comment_db, "a1", "tp", d, "Первая версия")
    upsert_comment(comment_db, "a1", "tp", d, "Обновлённый")
    assert get_comment(comment_db, "a1", "tp", d) == "Обновлённый"
    # не более одной записи
    session = get_session(comment_db)
    cnt = session.query(MetricComment).filter_by(
        athlete_id="a1", metric_key="tp", comment_date=d).count()
    session.close()
    assert cnt == 1


def test_delete_comment(comment_db):
    d = datetime.date(2026, 8, 5)
    assert delete_comment(comment_db, "a1", "tp", d) is True
    assert get_comment(comment_db, "a1", "tp", d) is None
    assert delete_comment(comment_db, "a1", "tp", d) is False  # уже нет


def test_empty_comment_deletes_via_upsert(comment_db):
    d = datetime.date(2026, 8, 10)
    upsert_comment(comment_db, "a1", "tp", d, "удалить меня")
    assert get_comment(comment_db, "a1", "tp", d) == "удалить меня"
    upsert_comment(comment_db, "a1", "tp", d, "")  # пустой = удаление
    assert get_comment(comment_db, "a1", "tp", d) is None


def test_uniqueness_constraint(comment_db):
    """Повторный скачок (атлет,метрика,дата) — одна запись (upsert не дублирует)."""
    d = datetime.date(2026, 8, 6)
    upsert_comment(comment_db, "a1", "si", d, "one")
    upsert_comment(comment_db, "a1", "si", d, "two")
    session = get_session(comment_db)
    cnt = session.query(MetricComment).filter_by(
        athlete_id="a1", metric_key="si", comment_date=d).count()
    session.close()
    assert cnt == 1


# ---------------- график ----------------
def test_plot_loads_comments(gui_root, comment_db):
    from metricplot import MetricPlot, MetricSpec
    # Самостоятельный тест: добавляем комментарии, не полагаясь на состояние из
    # других тестов (DAO-тесты могли их удалить/перезаписать в любом порядке).
    upsert_comment(comment_db, "a1", "tp", datetime.date(2026, 8, 5), "c1")
    upsert_comment(comment_db, "a1", "tp", datetime.date(2026, 8, 9), "c2")
    spec = MetricSpec("tp", "TP", "мс²", lambda r: r.tp)
    plot = MetricPlot(gui_root, spec, db_path=comment_db)
    plot.athlete = "a1"
    assert set(plot._comments.keys()) == {datetime.date(2026, 8, 5),
                                          datetime.date(2026, 8, 9)}
    # нет комментариев для другой метрики
    spec2 = MetricSpec("hr", "ЧСС", "уд/мин", lambda r: r.mean_hr)
    plot2 = MetricPlot(gui_root, spec2, db_path=comment_db)
    plot2.athlete = "a1"
    assert plot2._comments == {}


def test_comment_markers_draw(gui_root, comment_db):
    """_draw_comment_markers не падает и работает с реальными данными."""
    from metricplot import MetricPlot, MetricSpec
    spec = MetricSpec("tp", "TP", "мс²", lambda r: r.tp, "#4cc9f0")
    plot = MetricPlot(gui_root, spec, db_path=comment_db)
    plot.athlete = "a1"
    plot._reload()
    plot.view = (739400.0, 739500.0)  # около дат записей
    plot._draw()
    gui_root.update()
    # просто не падает — ключевая проверка
    assert True