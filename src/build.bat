@echo off
chcp 65001 >nul
echo === Сборка AnalysisHVR.exe ===

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller не установлен. Выполните: pip install pyinstaller
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --onedir --windowed --name "AnalysisHVR" ^
  --add-data "logo21.png;." ^
  --add-data "scripts\ecg_profiles.yaml;." ^
  --add-data "scripts\config.yaml;." ^
  --add-data "scripts\athlete_generator.py;scripts" ^
  --add-data "scripts\ecg_generator.py;scripts" ^
  --add-data "analysis.py;." ^
  --add-data "scripts\database.py;scripts" ^
  --add-data "scripts\models.py;scripts" ^
  --add-data "scripts\schedule_engine.py;scripts" ^
  --add-data "scripts\calibrate_ecg.py;scripts" ^
  --add-data "splash.py;." ^
  --add-data "theme.py;." ^
  --add-data "dialogs.py;." ^
  --add-data "analysis.py;." ^
  --collect-all customtkinter ^
  --hidden-import tkcalendar ^
  --hidden-import babel ^
  --hidden-import sqlalchemy ^
  --hidden-import athlete_generator ^
  --hidden-import analysis ^
  --hidden-import ecg_generator ^
  --hidden-import schedule_engine ^
  --hidden-import models ^
  --hidden-import database ^
  --hidden-import theme ^
  --hidden-import dialogs ^
  --hidden-import splash ^
  app.py

if errorlevel 1 (
    echo === ОШИБКА СБОРКИ ===
    pause
    exit /b 1
)

echo === Копирование базы данных ===
xcopy /E /I /Y data dist\AnalysisHVR\data

echo === Копирование скриптов ===
xcopy /E /I /Y scripts dist\AnalysisHVR\_internal\scripts

echo.
echo ✅ Готово: dist\AnalysisHVR\AnalysisHVR.exe
pause