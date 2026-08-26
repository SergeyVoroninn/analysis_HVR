"""
Тесты для модуля настроек приложения (appsettings.py).
Проверяют сохранение, загрузку и устойчивость к поврежденным файлам.
"""
import os
import sys
import json
import tempfile
import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from appsettings import AppSettings


@pytest.fixture
def temp_settings_file():
    """Создает временный файл для тестирования настроек."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)  # Закрываем дескриптор, чтобы AppSettings мог открыть файл
    yield path
    # Очистка после теста
    if os.path.exists(path):
        os.remove(path)
    tmp_path = path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)


def test_appsettings_save_and_load(temp_settings_file):
    """Проверка: сохраненные настройки корректно загружаются."""
    # 1. Создаем настройки с кастомным путем (используем 'path', как в реальном коде)
    settings = AppSettings(path=temp_settings_file)
    
    # 2. Сохраняем тестовые данные
    settings.set("athlete_id", "test_123")
    settings.set("year", 2024)
    settings.set("week", 15)
    settings.set("zoom", [738000, 738010])
    settings.save()
    
    # 3. Создаем новый экземпляр и загружаем
    new_settings = AppSettings(path=temp_settings_file).load()
    
    assert new_settings.get("athlete_id") == "test_123"
    assert new_settings.get("year") == 2024
    assert new_settings.get("week") == 15
    assert new_settings.get("zoom") == [738000, 738010]


def test_appsettings_load_missing_file(temp_settings_file):
    """Проверка: если файла нет, загружаются значения по умолчанию без ошибок."""
    # Гарантируем, что файла нет
    if os.path.exists(temp_settings_file):
        os.remove(temp_settings_file)
    
    settings = AppSettings(path=temp_settings_file).load()
    
    # Проверяем, что возвращаются дефолтные значения (None) и словарь пуст
    assert settings.get("athlete_id") is None
    assert settings.get("year") is None
    assert settings.get("zoom") is None
    assert settings.data == {}


def test_appsettings_load_corrupted_file(temp_settings_file):
    """Проверка: приложение не падает, если JSON-файл поврежден (ValueError)."""
    # Записываем невалидный JSON
    with open(temp_settings_file, 'w', encoding='utf-8') as f:
        f.write("{ this is not valid json: }")
    
    # Загрузка должна пройти без исключений, вернув пустые значения (благодаря except ValueError)
    settings = AppSettings(path=temp_settings_file).load()
    
    assert settings.get("athlete_id") is None
    assert settings.get("year") is None
    assert settings.data == {}