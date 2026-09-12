"""
test_timeframe.py — тесты для timeframe.py
"""
import sys
import os

# Добавляем родительскую директорию (src) в путь импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timeframe import get_chart_config, TimeFrame


def test_day_range():
    """Диапазон 1 день — MIN5 (5 минут)."""
    config = get_chart_config(1)
    print(f"  1 день: bar={config.bar_tf}, zebra={config.zebra_tf}")
    assert config.bar_tf is TimeFrame.MIN5
    assert config.zebra_tf is TimeFrame.HOUR1
    print("✓ Тест day_range пройден")


def test_half_day_range():
    """Диапазон 0.5 дня (12 часов) — MIN5."""
    config = get_chart_config(0.5)
    print(f"  0.5 дня: bar={config.bar_tf}, zebra={config.zebra_tf}")
    assert config.bar_tf is TimeFrame.MIN5
    print("✓ Тест half_day_range пройден")


def test_week_range():
    """Диапазон 3 дня — HOUR1 (1 час)."""
    config = get_chart_config(3)
    print(f"  3 дня: bar={config.bar_tf}, zebra={config.zebra_tf}")
    # ИСПРАВЛЕНО: для 3 дней должен быть HOUR1, а не WEEK
    assert config.bar_tf is TimeFrame.HOUR1
    assert config.zebra_tf is TimeFrame.DAY
    print("✓ Тест week_range пройден")


def test_7day_range():
    """Диапазон 7 дней — HOUR1."""
    config = get_chart_config(7)
    print(f"  7 дней: bar={config.bar_tf}, zebra={config.zebra_tf}")
    assert config.bar_tf is TimeFrame.HOUR1
    print("✓ Тест 7day_range пройден")


def test_month_range():
    """Диапазон до месяца — HOUR3."""
    config = get_chart_config(15)
    print(f"  15 дней: bar={config.bar_tf}, zebra={config.zebra_tf}")
    assert config.bar_tf is TimeFrame.HOUR3
    assert config.zebra_tf is TimeFrame.DAY
    print("✓ Тест month_range пройден")


def test_year_range():
    """Диапазон до года — DAY."""
    config = get_chart_config(200)
    print(f"  200 дней: bar={config.bar_tf}, zebra={config.zebra_tf}")
    assert config.bar_tf is TimeFrame.DAY
    assert config.zebra_tf is TimeFrame.WEEK
    assert config.tick_step_days == 30
    print("✓ Тест year_range пройден")


def test_over_year_range():
    """Диапазон больше года — пропорциональный режим."""
    config = get_chart_config(500)
    print(f"  500 дней: bar={config.bar_tf}, proportional={config.is_proportional}")
    assert config.is_proportional is True
    print("✓ Тест over_year_range пройден")


def test_boundary_week():
    """Граница: ровно 7 дней."""
    config = get_chart_config(7)
    print(f"  7 дней (граница): bar={config.bar_tf}")
    assert config.bar_tf is TimeFrame.HOUR1
    print("✓ Тест boundary_week пройден")


def test_boundary_month():
    """Граница: ровно 31 день."""
    config = get_chart_config(31)
    print(f"  31 день (граница): bar={config.bar_tf}")
    assert config.bar_tf is TimeFrame.HOUR3
    print("✓ Тест boundary_month пройден")


def test_boundary_year():
    """Граница: ровно 366 дней."""
    config = get_chart_config(366)
    print(f"  366 дней (граница): bar={config.bar_tf}, proportional={config.is_proportional}")
    assert config.bar_tf is TimeFrame.DAY
    assert not config.is_proportional
    print("✓ Тест boundary_year пройден")


if __name__ == "__main__":
    print("\n=== Тесты конфигурации timeframe ===\n")
    test_day_range()
    test_half_day_range()
    test_week_range()
    test_7day_range()
    test_month_range()
    test_year_range()
    test_over_year_range()
    test_boundary_week()
    test_boundary_month()
    test_boundary_year()
    print("\n✅ Все тесты пройдены!")