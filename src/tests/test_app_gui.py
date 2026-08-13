import tkinter as tk
import pytest
from models import get_session, Athlete


@pytest.mark.gui
def test_app_smoke(tmp_path):
    """Приложение стартует, грузит спортсменов, рисует графики."""
    db = str(tmp_path / "gui.db")
    s = get_session(db)
    s.add(Athlete(id="a1", last_name="Иванов", first_name="И",
                  birth_date="2008-01-01", gender="M", polar_id="P1"))
    s.commit()
    s.close()

    import app as app_module
    app_module._load_heavy()

    root = tk.Tk()
    root.withdraw()
    try:
        view = app_module.ECGViewerApp(root, db_path=db)
        root.update()

        assert len(view.athletes) == 1
        assert view.selected_athlete is not None
        assert view._week_start is not None      # heatmap построен

        view.destroy()
    finally:
        root.destroy()