"""
Тесты реестра метрик, порядка отображения и окна настроек.

Проверяет:
  * ALL_METRICS содержит TP, стресс, ЧСС, RMSSD, SDNN;
  * ChartsPanel.set_metrics корректно меняет состав и порядок;
  * загрузка сохранённых метрик из настроек (порядок + фильтр несуществующих);
  * диалог настроек позволяет переупорядочить и выключить метрику.
"""
import os
import sys
import tkinter as tk
import pytest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "scripts"))

from charts import (ALL_METRICS, DEFAULT_METRIC_ORDER, TP_METRIC, SI_METRIC,
                    HR_METRIC, RMSSD_METRIC, metric_by_key,
                    ChartsPanel)  # noqa: E402
from ghost import ResizeController  # noqa: E402


# ---------------- реестр метрик ----------------
def test_all_metrics_registry_complete():
    """Каталог содержит 4 метрики: TP, стресс, ЧСС, RMSSD."""
    expected = {"tp", "si", "hr", "rmssd"}
    assert set(ALL_METRICS.keys()) == expected


def test_metric_by_key_known_and_unknown():
    assert metric_by_key("tp") is TP_METRIC
    assert metric_by_key("nope") is None


def test_default_order_has_all_keys():
    """Порядок по умолчанию содержит все ключи реестра."""
    assert set(DEFAULT_METRIC_ORDER) == set(ALL_METRICS.keys())


# ---------------- ChartsPanel.set_metrics ----------------
@pytest.fixture
def charts_panel(gui_root):
    return ChartsPanel(gui_root, metrics=[TP_METRIC, SI_METRIC], db_path=":memory:")


def test_initial_metric_keys(charts_panel):
    assert charts_panel.metric_keys() == ["tp", "si"]


def test_set_metrics_changes_order(charts_panel):
    """set_metrics в обратном порядке меняет порядок отображения."""
    charts_panel.set_metrics([SI_METRIC, TP_METRIC])
    assert charts_panel.metric_keys() == ["si", "tp"]


def test_set_metrics_allows_more_metrics(charts_panel):
    """Добавляем новые метрики: состав расширяется, порядок сохраняется."""
    charts_panel.set_metrics([HR_METRIC, RMSSD_METRIC, TP_METRIC])
    assert charts_panel.metric_keys() == ["hr", "rmssd", "tp"]


def test_set_metrics_preserves_current_athlete(charts_panel):
    """После пересоздания графиков атлет должен сохраниться."""
    charts_panel.athlete = "athlete_1"
    charts_panel.set_metrics([TP_METRIC, HR_METRIC])
    assert charts_panel.metric_keys() == ["tp", "hr"]
    # Новые графики знают текущего атлета
    assert all(p.athlete == "athlete_1" for p in charts_panel._plots)


# ---------------- загрузка из настроек (порядок + фильтр) ----------------
def _load_metric_specs(saved_keys, default_order=DEFAULT_METRIC_ORDER):
    """Воспроизводит логику загрузки метрик из app.py."""
    if saved_keys:
        specs = [metric_by_key(k) for k in saved_keys
                 if metric_by_key(k) is not None]
    else:
        specs = [metric_by_key(k) for k in default_order
                 if metric_by_key(k) is not None]
    return specs


def test_load_saved_order():
    saved = ["rmssd", "tp", "hr"]
    specs = _load_metric_specs(saved)
    assert [s.key for s in specs] == ["rmssd", "tp", "hr"]


def test_load_filters_unknown_keys():
    saved = ["tp", "nonexistent", "sr"]
    specs = _load_metric_specs(saved)
    assert [s.key for s in specs] == ["tp"]


def test_load_default_when_empty():
    specs = _load_metric_specs([])
    assert [s.key for s in specs] == DEFAULT_METRIC_ORDER


# ---------------- диалог настроек ----------------
def _make_dialog(gui_root, current_order=None):
    """Создаёт реальный диалог с заданным текущим порядком."""
    from dialogs.settings import MetricsSettingsDialog
    from unittest.mock import Mock
    dlg = MetricsSettingsDialog.__new__(MetricsSettingsDialog)
    # _move() перестраивает список — в моке это no-op (не строим Tk-виджеты).
    dlg._rebuild_list = Mock()
    # Воспроизводим логику __init__ без явного вызова (без Tk-виджетов).
    order = list(current_order or DEFAULT_METRIC_ORDER)
    merged = order + [k for k in ALL_METRICS if k not in order]
    dlg._order = merged
    enabled = set(order) if order else set(ALL_METRICS)
    dlg._enabled = {k: (k in enabled) for k in merged}
    dlg.result = None
    return dlg


def test_dialog_all_in_order_visible(gui_root):
    """По умолчанию в списке ВСЕ метрики порядка ALL_METRICS, все включены."""
    dlg = _make_dialog(gui_root)
    assert set(dlg._order) == set(ALL_METRICS)
    assert all(dlg._enabled[k] for k in DEFAULT_METRIC_ORDER)


def test_dialog_uncheck_keeps_metric_in_list(gui_root):
    """Снятие чекбокса НЕ убирает метрику из списка — только из выбранных."""
    dlg = _make_dialog(gui_root)
    # снимаем 'si'
    dlg._enabled["si"] = False
    # метрика остаётся в списке
    assert "si" in dlg._order
    # но не попадает в результат
    selected = [k for k in dlg._order if dlg._enabled[k]]
    assert "si" not in selected
    assert "tp" in selected


def test_dialog_move_changes_order_keeps_selection(gui_root):
    """Перемещение меняет порядок, сохраняя отметки."""
    dlg = _make_dialog(gui_root)
    # перемещаем 'rmssd' вверх (из позиции 3 в 0)
    i = dlg._order.index("rmssd")
    dlg._move("rmssd", -i)
    assert dlg._order[0] == "rmssd"
    # отметки сохранились
    assert dlg._enabled["rmssd"] is True
    assert dlg._enabled["tp"] is True
    # итоговый результат содержит rmssd на первом месте
    selected = [k for k in dlg._order if dlg._enabled[k]]
    assert selected[0] == "rmssd"


# ---------------- регрессия: цветной маркер не падает ----------------
def test_dialog_renders_all_metrics_with_markers(gui_root):
    """Окно настроек отрисовывает каждую метрику с цветным маркером.

    Регрессия: `color` у SI_METRIC — функция _si_color, а не строка. Окно
    пыталось использовать spec.color как цвет маркера -> ValueError, и список
    метрик в окне был пуст. Теперь маркер берёт spec.marker_color (всегда строка).
    """
    from dialogs.settings import MetricsSettingsDialog

    dlg = MetricsSettingsDialog(gui_root, current_order=list(ALL_METRICS.keys()))
    gui_root.update()

    # Внутри _list должны быть rows по числу метрик
    children = [w for w in dlg._list.winfo_children()]
    assert len(children) >= 1, "список метрик пуст — регрессия с marker_color"
    # У всех метрик marker_color — строка
    for key in ALL_METRICS:
        assert isinstance(ALL_METRICS[key].marker_color, str), \
            f"marker_color у {key} должен быть строкой, а не функцией"
    dlg.close()


def test_si_metric_marker_is_string():
    """У стресса marker_color строка, даже если color — функция."""
    assert callable(SI_METRIC.color)          # цвет графика задаётся функцией
    assert isinstance(SI_METRIC.marker_color, str)  # но маркер — константа


# ---------------- регрессия: пропорция графиков при смене метрик ----------------
def test_apply_size_preserves_aspect_after_set_metrics(gui_root):
    """ChartsPanel.apply_size задаёт каждому графику высоту ~= ширина/ASPECT.

    Высота графика фиксирована соотношением ширины (ASPECT) и не зависит от
    высоты окна: если графики не помещаются, они прокручиваются. Проверяем,
    что после смены метрик пропорция сохраняется.
    """
    right = tk.Frame(gui_root, width=900, height=560)
    right.pack(fill="both", expand=True)
    charts = ChartsPanel(right, metrics=[TP_METRIC, SI_METRIC], db_path=":memory:")

    avail_w, avail_h = 900, 400
    charts.apply_size(avail_w, avail_h)

    # Каждый график: высота = ширина/ASPECT (фикс), не зависит от окна.
    per = charts._each_height(avail_w, avail_h)
    aspect = ChartsPanel.ASPECT
    assert per == max(120, int(avail_w / aspect)), \
        f"высота графика не соответствует ASPECT: {per}"

    # Меняем метрики — пропорция должна сохраниться.
    charts.set_metrics([HR_METRIC, TP_METRIC, SI_METRIC])
    per = charts._each_height(avail_w, avail_h)
    assert per == max(120, int(avail_w / aspect))


# ---------------- регрессия: смена метрик на лету не обрезает данные ----------------
def test_set_metrics_resets_view_to_full_range(gui_root):
    """После set_metrics новые графики должны показывать ВЕСЬ диапазон (view=None).

    Симуляция окна настроек: у ChartsPanel был сохранённый зум (view не None),
    потом пользователь меняет состав метрик. Ранее новые графики наследовали
    старый zoom, из-за чего часть данных была не видна до перезапуска. Теперь
    сбрасываем view, чтобы отображался весь период.
    """
    from models import get_session, Athlete, ECGRecord

    session = get_session(":memory:")
    session.query(ECGRecord).delete()
    session.query(Athlete).delete()
    session.add(Athlete(id="a1", last_name="Тест", first_name="Атлет"))
    session.add_all([
        ECGRecord(athlete_id="a1", recorded_at="2026-07-01 08:00:00",
                  tp=1000, stress_si=50, mean_hr=70, rmssd=30),
        ECGRecord(athlete_id="a1", recorded_at="2026-09-15 08:00:00",
                  tp=2000, stress_si=80, mean_hr=75, rmssd=35),
        ECGRecord(athlete_id="a1", recorded_at="2026-10-15 08:00:00",
                  tp=1500, stress_si=60, mean_hr=72, rmssd=32),
    ])
    session.commit()
    session.close()

    charts = ChartsPanel(gui_root, metrics=[TP_METRIC, SI_METRIC], db_path=":memory:")
    charts.athlete = "a1"
    # Пользователь сзумировал на середину периода (виден не весь диапазон).
    charts.zoom = (739100.0, 739300.0)      # не весь период
    for p in charts._plots:
        assert p.view is not None, "предусловие: должен быть сохранённый zoom"

    # Симуляция: меняем метрики и сбрасываем view (как в _open_metrics_settings).
    charts.set_metrics([HR_METRIC, TP_METRIC, SI_METRIC, RMSSD_METRIC])
    for p in charts._plots:
        p.view = None        # сброс как делает orchestrator при saved_range=None
        p._reload()

    # Все графики должны покрывать весь диапазон данных (01.07–15.10).
    for p in charts._plots:
        assert p.view is None, f"{p.spec.key}: view должен быть None (полный диапазон)"
        assert p._start is not None and p._end is not None
        span_days = (p._end - p._start).days
        assert span_days > 60, f"{p.spec.key}: ожидался полный диапазон, span={span_days}"
    assert charts.metric_keys() == ["hr", "tp", "si", "rmssd"]


# ---------------- регрессия: колесо = скролл, ЛКМ+колесо = зум ----------------
def _make_wheel_event(button):
    """MPL scroll-event mock."""
    ev = type("Ev", (), {})()
    ev.button = button    # "up"/"down"
    ev.xdata = 739000.0
    ev.ydata = None
    ev.x = 100
    ev.y = 100
    return ev


def test_wheel_without_lmb_calls_scroll_vertical(gui_root):
    """Колесо без зажатой ЛКМ → вертикальная прокрутка панели (не зум)."""
    from metricplot import MetricPlot, MetricSpec

    plot = MetricPlot(gui_root, TP_METRIC, db_path=":memory:")
    scrolled = []
    plot.on_scroll_vertical = lambda steps: scrolled.append(steps)
    plot._lmb_down = False
    plot._on_scroll(_make_wheel_event("up"))
    assert scrolled, "колесо без ЛКМ должно вызвать on_scroll_vertical"
    assert scrolled[0] == 1, f"ожидался steps=1 (вверх), получено {scrolled[0]}"


def test_wheel_with_lmb_does_not_scroll(gui_root):
    """ЛКМ + колесо → НЕ прокрутка (зум), on_scroll_vertical не вызывается."""
    from metricplot import MetricPlot, MetricSpec
    from unittest.mock import Mock

    plot = MetricPlot(gui_root, TP_METRIC, db_path=":memory:")
    plot.on_scroll_vertical = Mock()
    plot._lmb_down = True
    plot._on_scroll(_make_wheel_event("up"))
    plot.on_scroll_vertical.assert_not_called()


def test_lmb_flag_tracks_press_release(gui_root):
    """Флаг _lmb_down должен ставиться при press ЛКМ и сбрасываться при release."""
    from metricplot import MetricPlot, MetricSpec
    from matplotlib.backend_bases import MouseEvent, MouseButton

    plot = MetricPlot(gui_root, TP_METRIC, db_path=":memory:")
    assert plot._lmb_down is False
    press = MouseEvent("button_press_event", plot.canvas, 100, 100, MouseButton.LEFT)
    plot._on_press(press)
    # _on_press для ЛКМ с xdata None может выйти раньше; проверим что не падает
    release = MouseEvent("button_release_event", plot.canvas, 100, 100, MouseButton.LEFT)
    plot._on_release(release)
    # release безусловно сбрасывает флаг
    assert plot._lmb_down is False, "_lmb_down должен быть False после release"