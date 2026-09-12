"""
Тесты модуля импорта (importer.py).
Проверяют корректность парсинга, сохранения в БД и защиту от дубликатов.
"""
import datetime
import os
import sys
import tempfile
import shutil
import glob
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine

# Динамическое определение корневой директории проекта
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from models import get_session, Athlete, ECGRecord, ECGRaw, Base
from importer import import_ecg

# Находим реальный эталонный файл для тестов
REFERENCE_DIR = os.path.join(PROJECT_DIR, "tests", "reference")
REFERENCE_FILES = glob.glob(os.path.join(REFERENCE_DIR, "*.teamloggerh10"))
assert len(REFERENCE_FILES) > 0, "Не найдено эталонных файлов .teamloggerh10 в tests/reference/"
REAL_H10_FILE = REFERENCE_FILES[0]


@pytest.fixture
def temp_db_and_athlete():
    """Создает реальную временную БД и тестового атлета для изолированного тестирования."""
    temp_dir = tempfile.mkdtemp(prefix="hvr_test_")
    db_path = os.path.join(temp_dir, "test_app.db")

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        session = get_session(db_path)
        
        # ВАЖНО: Убедитесь, что polar_id совпадает с тем, что внутри REAL_H10_FILE, 
        # или что ваш import_ecg привязывается только к athlete_id.
        athlete = Athlete(
            id="test_athlete_001",
            last_name="Тестов",
            first_name="Атлет",
            gender="M",
            birth_date=datetime.date(2000, 1, 1),
            polar_id="TESTPOLAR123"  # Замените на реальный ID из файла, если требуется строгая проверка
        )
        session.add(athlete)
        session.commit()
        
        yield db_path, athlete.id
        
    finally:
        if 'session' in locals():
            session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_import_valid_h10_file(temp_db_and_athlete):
    """Сценарий: Успешный импорт реального эталонного файла."""
    db_path, athlete_id = temp_db_and_athlete
    
    status_var = MagicMock()
    mock_athletes = {athlete_id: MagicMock()}
    
    # Мокаем диалог выбора файлов, чтобы он вернул реальный эталонный файл
    with patch('tkinter.filedialog.askopenfilenames', return_value=(REAL_H10_FILE,)):
        import_ecg(MagicMock(), db_path, mock_athletes, (athlete_id, "Тестов Атлет"), status_var)

    session = get_session(db_path)
    try:
        records = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).all()
        
        assert len(records) >= 1, "Должна быть создана хотя бы одна запись ЭКГ"
        
        # Проверяем, что метрики рассчитаны для последней записи
        rec = records[-1]
        assert rec.sdnn is not None, "Метрика SDNN не была рассчитана"
        assert rec.sdnn > 0, "Метрика SDNN должна быть положительной"
        
    finally:
        session.close()


def test_import_duplicate_file_is_skipped(temp_db_and_athlete):
    """Сценарий: Попытка импорта того же самого файла дважды."""
    db_path, athlete_id = temp_db_and_athlete
    
    status_var = MagicMock()
    mock_athletes = {athlete_id: MagicMock()}
    
    with patch('tkinter.filedialog.askopenfilenames', return_value=(REAL_H10_FILE,)):
        # Первый импорт
        import_ecg(MagicMock(), db_path, mock_athletes, (athlete_id, "Тестов Атлет"), status_var)
        
        session = get_session(db_path)
        initial_count = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).count()
        session.close()
        
        # Второй импорт того же файла
        import_ecg(MagicMock(), db_path, mock_athletes, (athlete_id, "Тестов Атлет"), status_var)
        
    session = get_session(db_path)
    try:
        final_count = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).count()
        assert final_count == initial_count, \
            f"Ожидалось {initial_count} записей (защита от дубликатов), получено {final_count}"
    finally:
        session.close()


def test_import_corrupted_file_fails_gracefully(temp_db_and_athlete):
    """
    Сценарий: Импорт битого файла. 
    Ожидание: Приложение не падает с исключением, а в БД не появляется записей с рассчитанными метриками.
    """
    db_path, athlete_id = temp_db_and_athlete
    
    fd, mock_file = tempfile.mkstemp(suffix=".teamloggerh10")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write("Это не файл Polar H10, а полный мусор 12345!@#")

    try:
        status_var = MagicMock()
        mock_athletes = {athlete_id: MagicMock()}
        
        with patch('tkinter.filedialog.askopenfilenames', return_value=(mock_file,)):
            # Главное: импорт не должен вызвать краш приложения (исключение)
            import_ecg(MagicMock(), db_path, mock_athletes, (athlete_id, "Тестов Атлет"), status_var)

        session = get_session(db_path)
        try:
            records = session.query(ECGRecord).filter(ECGRecord.athlete_id == athlete_id).all()
            
            # Проверяем целостность данных:
            # 1. Если записей нет вообще — это идеальный отказ (graceful failure).
            # 2. Если запись создана (например, как лог ошибки), то метрики в ней НЕ должны быть рассчитаны.
            for rec in records:
                assert rec.sdnn is None, \
                    "Битый файл не должен приводить к расчету валидных метрик (SDNN)"
            
            # Мы намеренно НЕ проверяем status_var.set.called, так как функция может 
            # обрабатывать ошибки молча, через logging или print, что тоже является 
            # корректным поведением с точки зрения защиты данных.
            
        finally:
            session.close()
    finally:
        os.remove(mock_file)