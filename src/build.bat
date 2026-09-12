@echo off
chcp 65001 >nul
echo ============================================
echo === Сборка AnalysisHVR.exe ===
echo ============================================

:: Опция быстрой сборки: build.bat --fast (пропустить тесты)
set RUN_TESTS=1
if "%1"=="--fast" set RUN_TESTS=0

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller не установлен. Выполните: pip install pyinstaller
    pause
    exit /b 1
)

:: ============================================================
:: ШАГ 1/3: ТЕСТЫ
:: ============================================================
if %RUN_TESTS%==1 (
    echo.
    echo === Шаг 1/3: Запуск тестов ===
    python -m pytest tests -q
    if errorlevel 1 (
        echo.
        echo ❌ ТЕСТЫ НЕ ПРОШЛИ — сборка прервана
        echo    Исправьте ошибки и запустите build.bat снова
        pause
        exit /b 1
    )
    echo ✅ Все тесты прошли
) else (
    echo.
    echo === Шаг 1/3: Тесты пропущены (--fast) ===
)

:: ============================================================
:: ШАГ 2/3: СБОРКА EXE
:: ============================================================
echo.
echo === Шаг 2/3: Сборка exe ===
python -m PyInstaller --noconfirm --onedir --windowed --name "AnalysisHVR" ^
  --paths scripts ^
  --add-data "logo21.png;." ^
  --add-data "scripts\ecg_profiles.yaml;." ^
  --add-data "scripts\config.yaml;." ^
  --collect-all customtkinter ^
  --hidden-import splash ^
  --hidden-import theme ^
  --hidden-import dialogs ^
  --hidden-import analysis ^
  --hidden-import athlete_generator ^
  --hidden-import ecg_generator ^
  --hidden-import schedule_engine ^
  --hidden-import models ^
  --hidden-import database ^
  --hidden-import tkcalendar ^
  --hidden-import babel ^
  --hidden-import sqlalchemy ^
  app.py

if errorlevel 1 (
    echo === ОШИБКА СБОРКИ ===
    pause
    exit /b 1
)

:: ============================================================
:: ШАГ 3/3: БАЗА ДАННЫХ
:: ============================================================
echo.
echo === Шаг 3/3: Копирование базы данных ===
xcopy /E /I /Y data dist\AnalysisHVR\data

echo.
echo ✅ Готово: dist\AnalysisHVR\AnalysisHVR.exe
pause