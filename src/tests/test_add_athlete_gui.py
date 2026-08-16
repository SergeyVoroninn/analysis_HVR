"""E2E-тест GUI: добавление спортсмена через настоящий AthleteDialog."""
import datetime
import os
import sys
import time

import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

import app as app_module
import dialogs as dialogs_module


@pytest.fixture(scope="module")
def _heavy():
    app_module._load_heavy()


@pytest.fixture()
def app(_heavy, tmp_path):
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    window = app_module.ECGViewerApp(root, db_path=str(tmp_path / "test.db"))
    root.update()
    yield window
    for w in (window, root):
        try:
            w.destroy()
        except Exception:
            pass


# ---------- хелперы ----------
def _find_button(widget, text):
    stack = [widget]
    while stack:
        w = stack.pop()
        try:
            if str(w.cget("text")) == text:
                return w
        except Exception:
            pass
        stack.extend(w.winfo_children())
    return None


def _find_dialog(app):
    for w in app.winfo_children():
        if isinstance(w, app_module.AthleteDialog):
            return w
    return None


def _db_athlete(app, last_name):
    session = app_module.get_session(app.db_path)
    try:
        return session.query(app_module.Athlete).filter_by(last_name=last_name).one()
    finally:
        session.close()


# ---------- тесты ----------
def test_add_athlete_fields_match(app):
    """Заполняем настоящий диалог → сохраняем → поля в списке и БД совпадают."""
    def drive():
        dlg = _find_dialog(app)
        assert dlg is not None, "диалог не открылся"
        dlg.entries["last_name"].insert(0, "Сидорова")
        dlg.entries["first_name"].insert(0, "Анна")
        dlg.entries["middle_name"].insert(0, "Сергеевна")
        dlg.birth_date_entry.set_date(datetime.date(2008, 3, 12))
        dlg.gender_var.set("F")
        dlg.entries["height_cm"].insert(0, "152")
        dlg.entries["weight_kg"].insert(0, "47.5")
        dlg.entries["polar_id"].insert(0, "ABCD1234")
        (getattr(dlg, "btn_save", None) or _find_button(dlg, "Сохранить")).invoke()

    app.after(150, drive)
    _find_button(app, "＋").invoke()     # честный клик по «＋»
    app.update()

    # --- Treeview: ФИО и возраст ---
    expected_age = app_module._calc_age(datetime.date(2008, 3, 12))
    rows = [app.tree_athletes.item(i)["values"] for i in app.tree_athletes.get_children()]
    assert ["Сидорова Анна", expected_age] in rows

    # --- БД: каждое поле совпадает с введённым ---
    a = _db_athlete(app, "Сидорова")
    assert a.first_name == "Анна"
    assert a.middle_name == "Сергеевна"
    assert a.gender == "F"
    assert a.birth_date == "2008-03-12"
    assert a.height_cm == 152            # int-каст диалога
    assert a.weight_kg == pytest.approx(47.5)
    assert a.polar_id == "ABCD1234"


def test_add_athlete_autofill(app):
    """Пустые рост/вес/polar_id → оценочные значения, не NULL."""
    def drive():
        dlg = _find_dialog(app)
        dlg.entries["last_name"].insert(0, "Петров")
        dlg.entries["first_name"].insert(0, "Пётр")
        (getattr(dlg, "btn_save", None) or _find_button(dlg, "Сохранить")).invoke()

    app.after(150, drive)
    _find_button(app, "＋").invoke()
    app.update()

    a = _db_athlete(app, "Петров")
    assert a.height_cm and a.weight_kg
    assert a.polar_id and len(a.polar_id) >= 8
    assert a.resting_hr and a.max_hr


def test_add_athlete_validation(app, monkeypatch):
    """Пустое имя → предупреждение, диалог не закрыт, запись не создана."""
    warnings = []
    class FakeBox:
        @staticmethod
        def showwarning(title, msg):
            warnings.append(msg)
    monkeypatch.setattr(dialogs_module, "messagebox", FakeBox)

    def drive():
        dlg = _find_dialog(app)
        dlg.entries["last_name"].insert(0, "БезИмени")
        # имя не заполняем
        (getattr(dlg, "btn_save", None) or _find_button(dlg, "Сохранить")).invoke()
        assert warnings, "валидация не сработала"
        assert dlg.winfo_exists(), "диалог должен остаться открытым"
        dlg.destroy()

    app.after(150, drive)
    _find_button(app, "＋").invoke()
    app.update()

    session = app_module.get_session(app.db_path)
    try:
        assert session.query(app_module.Athlete).count() == 0
    finally:
        session.close()

def test_add_athlete_calendar_interaction(app):
    """Открываем календарь, меняем месяц/год, диалог не закрывается."""
    def drive():
        dlg = _find_dialog(app)
        assert dlg is not None

        # Заполняем обязательные поля
        dlg.entries["last_name"].insert(0, "Календарев")
        dlg.entries["first_name"].insert(0, "Тест")

        # Открываем календарь
        cal = dlg.birth_date_entry
        cal.event_generate('<Button-1>', x=10, y=10)
        app.update()
        app.update_idletasks()
        time.sleep(0.3)

        # Диалог всё ещё открыт
        assert dlg.winfo_exists(), "диалог закрылся при открытии календаря"

        # Навигация по календарю: стрелка вперёд
        cal.event_generate('<Button-1>', x=cal.winfo_width() - 20, y=10)
        app.update()
        time.sleep(0.2)
        assert dlg.winfo_exists(), "диалог закрылся при навигации вперёд"

        # Навигация назад
        cal.event_generate('<Button-1>', x=20, y=10)
        app.update()
        time.sleep(0.2)
        assert dlg.winfo_exists(), "диалог закрылся при навигации назад"

        # Закрываем календарь и сохраняем
        cal.event_generate('<Escape>')
        app.update()
        (getattr(dlg, "btn_save", None) or _find_button(dlg, "Сохранить")).invoke()

    app.after(150, drive)
    _find_button(app, "＋").invoke()
    app.update()

    # Проверяем, что спортсмен создан
    session = app_module.get_session(app.db_path)
    try:
        assert session.query(app_module.Athlete).filter_by(last_name="Календарев").one()
    finally:
        session.close()

def test_add_athlete_future_birth_date(app, monkeypatch):
    """Будущая дата рождения → предупреждение, диалог не закрыт, запись не создана."""
    warnings = []
    class FakeBox:
        @staticmethod
        def showwarning(title, msg):
            warnings.append(msg)
    monkeypatch.setattr(dialogs_module, "messagebox", FakeBox)

    future_date = datetime.date.today() + datetime.timedelta(days=3650)  # +10 лет

    def drive():
        dlg = _find_dialog(app)
        assert dlg is not None, "диалог не открылся"

        # Заполняем обязательные поля
        dlg.entries["last_name"].insert(0, "Будущий")
        dlg.entries["first_name"].insert(0, "Иван")

        # Устанавливаем будущую дату (bypass календаря — проверяем валидацию)
        dlg.birth_date_entry.set_date(future_date)

        # Сохраняем
        (getattr(dlg, "btn_save", None) or _find_button(dlg, "Сохранить")).invoke()
        app.update()

        # === Проверки ===
        assert warnings, "предупреждение о некорректной дате не показано"
        assert "дата рождения" in warnings[0].lower() or "некорректная" in warnings[0].lower()
        assert dlg.winfo_exists(), "диалог должен остаться открытым после ошибки валидации"
        dlg.destroy()

    app.after(150, drive)
    _find_button(app, "＋").invoke()
    app.update()

    # === В БД не должно быть ни одной записи ===
    session = app_module.get_session(app.db_path)
    try:
        assert session.query(app_module.Athlete).count() == 0
    finally:
        session.close()