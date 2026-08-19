"""
appsettings.py — сохранение/восстановление состояния приложения (app).

Хранит в JSON-файле рядом с БД:
  athlete_id  — id последнего выбранного спортсмена;
  year        — текущий год на yearmap;
  week        — положение курсора недели (0..52 или None);
  zoom        — окно видимости графиков [lo, hi] в днях (или None = весь период).

Файл лежит отдельно от ecg.db, поэтому переживает подмену базы: если
атлета из настроек в новой базе нет — выбирается первый.
"""
import json
import os

from database import get_db_path


def settings_path():
    db = get_db_path()
    return os.path.join(os.path.dirname(db), "app_settings.json")


class AppSettings:
    def __init__(self, path=None):
        self.path = path or settings_path()
        self.data = {}

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        return self

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
