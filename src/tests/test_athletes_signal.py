"""
Тест-регрессия: панель атлетов сама уведомляет оркестратор о выбранном атлете
при построении/перезагрузке списка (первый запуск).

История бага: при первом запуске панель завершала выбор атлета ДО того, как в
app.py назначалась связка `panel.on_select = orchestrator.sync_athlete`, поэтому
событие выбора не доходило до оркестратора, и heatmap/графики не наполнялись
данными. Теперь панель в конце `reload()` вызывает `_notify_selected()` -> on_select.
"""
import os
import sys
import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from models import get_session, Athlete  # noqa: E402


@pytest.fixture(scope="session")
def athlete_db():
    """In-memory БД с двумя атлетами (одна на сессию: get_session(:memory:) персистентна)."""
    session = get_session(":memory:")
    session.query(Athlete).delete()
    session.add_all([
        Athlete(id="a1", last_name="Иванов", first_name="Иван"),
        Athlete(id="a2", last_name="Петров", first_name="Пётр"),
    ])
    session.commit()
    session.close()
    return ":memory:"


def test_panel_reload_notifies_orchestrator(gui_root, athlete_db):
    """reload() после назначения on_select отправляет выбранного атлета в колбэк."""
    from atlets import AthletesPanel

    # Назначаем колбэк ДО reload (как теперь в app.py: on_select = sync_athlete)
    received = []
    panel = AthletesPanel(gui_root, db_path=athlete_db, on_select=lambda aid: received.append(aid))
    gui_root.update()

    # При создании панель выполняет reload и выбирает первого атлета -> сигнал
    assert received, "панель не отправила сигнал о выбранном атлете"
    assert received[0] == "a1", f"ожидался первый атлет a1, получено {received[0]}"


def test_panel_reload_select_id_notifies(gui_root, athlete_db):
    """reload(select_id=...) отправляет выбранного атлета в on_select."""
    from atlets import AthletesPanel

    received = []
    panel = AthletesPanel(gui_root, db_path=athlete_db)
    gui_root.update()
    panel.on_select = lambda aid: received.append(aid)

    panel.reload(select_id="a2")
    gui_root.update()

    assert received, "reload(select_id) не отправил сигнал"
    assert received[-1] == "a2", f"ожидался a2, получено {received[-1]}"


def test_panel_no_signal_without_callback(gui_root, athlete_db):
    """Без назначенного on_select reload не падает и не шлёт сигнал."""
    from atlets import AthletesPanel

    panel = AthletesPanel(gui_root, db_path=athlete_db)
    gui_root.update()
    panel.on_select = None
    panel.reload()  # не должно упасть
    gui_root.update()