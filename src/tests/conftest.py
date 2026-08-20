import os
import sys
import pytest

"""
conftest.py — общие фикстуры для тестов.
"""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, BASE_DIR)


# Добавляем src в sys.path, чтобы импортировать модули
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def mock_metric_plot(mocker):
    """Фикстура: создаёт MetricPlot с mock-канвасом и ax."""
    from metricplot import MetricPlot, MetricSpec
    
    spec = MetricSpec("test", "Test", "unit", lambda r: r.value)
    
    # Создаём экземпляр без вызова __init__ (обходим Tk)
    plot = MetricPlot.__new__(MetricPlot)
    plot.spec = spec
    plot._current_tf = None
    plot.MIN_BAR_PX = 4
    plot.MAX_BAR_PX = 40
    plot.view = None
    plot.on_view_changed = None
    plot._draw = mocker.Mock()
    
    # Mock matplotlib ax
    plot.ax = mocker.Mock()
    mock_extent = mocker.Mock()
    mock_extent.width = 1000
    plot.ax.get_window_extent = mocker.Mock(return_value=mock_extent)
    
    return plot