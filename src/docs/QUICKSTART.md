# analysis_HVR
## Стартап датчики контроля состояния спортсмена

Для запуска проекта нужны 6 внешних библиотек. Всё остальное (os, sys, sqlite3, datetime, uuid, random, math) входит в стандартную библиотеку Python.

| Библиотека | Для чего |
| --- | --- |
| customtkinter | GUI приложения (app.py, dialogs.py) |
| matplotlib | Графики TP и стресса |
| tkcalendar | Виджет календаря для ввода даты рождения |
| sqlalchemy | ORM для работы с БД (models.py) |
| pyyaml | Чтение config.yaml и ecg_profiles.yaml |
| numpy | Анализ сигнала ЭКГ и RR-интервалов |

### Установка одной командой

```bash
pip install customtkinter matplotlib tkcalendar sqlalchemy pyyaml numpy
```

Или через requirements.txt
Создайте файл requirements.txt в корне проекта:

```txt
customtkinter>=5.2.0
matplotlib>=3.7.0
tkcalendar>=1.6.1
sqlalchemy>=2.0.0
pyyaml>=6.0
numpy>=1.24.0
```

```bash
pip install -r requirements.txt
```

### Проверка установки
```bash
python -c "import customtkinter, matplotlib, tkcalendar, sqlalchemy, yaml, numpy; print('✅ Все библиотеки установлены')"
```

Если всё ок — можно запускать:

```bash
cd src/scripts
python prepare_database.py
cd ..
python app.py
```
## 📸 Скриншоты

![Подготовка тестовых данных](images/prepare_database.png)
*Рисунок 1. Командная строка. Подготовка иестовых данных с помощью скрипта.*

![Главное окно приложения](images/app_main.png)
*Рисунок 2. Главное окно приложения анализа ВРС*

### Годовой heatmap

<p align="center">
  <img src="images/year_heatmap.png" alt="Годовой heatmap" />
</p>

Кликайте по квадратам, чтобы выбрать неделю 
<p align="center">
  <img src="images/week_heatmap.png" alt="Недельный heatmap" />
</p>

и просмотреть ЭКГ-записи.

![Главное окно приложения](images/ecg_list.png)
*Рисунок 3. Список записей в трехчасовой ячейке*

![Главное окно приложения](images/athlet_edit.png)
*Рисунок 4. Окно редактирования/добавления аилета*

![Главное окно приложения](images/app_import.png)
*Рисунок 5. Импорт файла записи с датчика*

## Настрока тестового профиля атлета

```txt
профиль спортсмена (rmssd, RR) → генератор ECG/RR → БД → графики
        ↑                                                    ↓
   физиологичные оценки  ←──────────────────────────  метрики TP/ИС
```   

Файл src/scripts/config.yaml управляет генерацией тестовых данных: составом команды, параметрами спортсменов и расписанием записей.

```txt
# ============================================================
# ГЛОБАЛЬНЫЕ НАСТРОЙКИ
# ============================================================
settings:
  duration_seconds: 12.0        # Длительность каждой записи ЭКГ (сек)
  db_path: null                 # Путь к БД (null = дефолт ../data/ecg.db)
  store_raw_data: true          # Сохранять raw ECG в БД (true/false)
  seed: 42                      # Seed для воспроизводимости (null = случайность)

# ============================================================
# СПИСОК СПОРТСМЕНОВ
# ============================================================
team:
  - { birth_year: 2008, gender: M, profile: regular_mwf_morning }
  - { birth_year: 2010, gender: F, profile: daily_evening }
  - { birth_year: 2005, gender: M, profile: regular_mwf_morning }
  # ... добавьте сколько нужно

# ============================================================
# ПРОФИЛИ РАСПИСАНИЙ
# ============================================================
profiles:
  regular_mwf_morning:
    days: [0, 2, 4]             # Пн=0, Вт=1, Ср=2, Чт=3, Пт=4, Сб=5, Вс=6
    hour: 9
    minute: 0
    
  daily_evening:
    days: [0, 1, 2, 3, 4, 5, 6] # Каждый день
    hour: 18
    minute: 30
    
  weekend_only:
    days: [5, 6]                # Только выходные
    hour: 10
    minute: 0
```

### Параметры спортсмена
| Параметр | Тип | Описание | Влияние на графики |
| --- | --- | --- | --- |
| birth_year | int | Год рождения (2005–2015) | Возраст → RMSSD: молодые (12–15 лет) имеют RMSSD 60–90, старшие (18+) — 40–60 |
| gender | str | Пол: M или F | Влияет на рост/вес/пульс покоя (женщины +5 уд/мин) |
| profile | str | Название профиля из секции profiles | Определяет расписание записей |


### Как возраст влияет на метрики

```txt
Возраст    →  _estimate_hrv_rmssd(age)  →  TP ≈ SDNN²  →  ИС
────────────────────────────────────────────────────────────────
12–14      →  70–90 мс                   →  5000–8000   →  25–40 🟢
15–17      →  60–80 мс                   →  3600–6400   →  35–50 🟢
18–22      →  50–70 мс                   →  2500–4900   →  45–65 🟡
23+        →  40–60 мс                   →  1600–3600   →  60–85 🟡
```

### Параметры профиля расписания

| Параметр | Тип | Описание |
| --- | --- | --- |
| days | list[int] | Дни недели: 0 = Пн, 1 = Вт, ..., 6 = Вс |
| hour | int | Час записи (0–23) |
| minute | int | Минута записи (0–59) |

## Типичные сценарии
## 1. Команда подростков (12–15 лет)

```yaml
settings:
  duration_seconds: 12.0
  seed: 42

team:
  - { birth_year: 2012, gender: M, profile: regular_mwf_morning }
  - { birth_year: 2011, gender: F, profile: regular_mwf_morning }
  - { birth_year: 2013, gender: M, profile: regular_mwf_morning }
  - { birth_year: 2010, gender: F, profile: regular_mwf_morning }
  - { birth_year: 2012, gender: M, profile: regular_mwf_morning }

profiles:
  regular_mwf_morning:
    days: [0, 2, 4]
    hour: 9
    minute: 0
```
Ожидаемые графики: TP 5000–8000, ИС 25–45 (зелёно-жёлтая зона)

## 2. Взрослые спортсмены (18–25 лет)
```yaml
settings:
  duration_seconds: 12.0
  seed: 42

team:
  - { birth_year: 2005, gender: M, profile: daily_evening }
  - { birth_year: 2003, gender: F, profile: daily_evening }
  - { birth_year: 2006, gender: M, profile: daily_evening }
  - { birth_year: 2004, gender: F, profile: daily_evening }

profiles:
  daily_evening:
    days: [0, 1, 2, 3, 4, 5, 6]
    hour: 19
    minute: 0
```
Ожидаемые графики: TP 2500–5000, ИС 45–70 (жёлто-оранжевая зона)

## 3. Смешанная команда с разными профилями
```yaml
settings:
  duration_seconds: 12.0
  seed: 42

team:
  # Молодые (утренние тренировки)
  - { birth_year: 2012, gender: M, profile: morning_training }
  - { birth_year: 2011, gender: F, profile: morning_training }
  
  # Старшие (вечерние тренировки)
  - { birth_year: 2005, gender: M, profile: evening_training }
  - { birth_year: 2003, gender: F, profile: evening_training }
  
  # Тренер (только выходные)
  - { birth_year: 1990, gender: M, profile: weekend_only }

profiles:
  morning_training:
    days: [0, 2, 4]
    hour: 8
    minute: 0
    
  evening_training:
    days: [1, 3, 5]
    hour: 18
    minute: 30
    
  weekend_only:
    days: [5, 6]
    hour: 10
    minute: 0
```

## Параметр seed

```yaml
seed: 42          # Воспроизводимая генерация
seed: null        # Случайная генерация (каждый запуск разные данные)
```

- seed: 42 — при каждом python prepare_database.py генерируются одинаковые данные (полезно для отладки)
- seed: null — каждый раз случайные данные (полезно для разнообразия)

## Параметр store_raw_data
```yaml
store_raw_data: true   # Сохранять raw ECG (10–50 КБ на запись)
store_raw_data: false  # Не сохранять (экономия места, но нельзя экспортировать)
```

| Значение | Размер БД (3000 записей) | Экспорт ЭКГ |
| --- | --- | --- |
| `true` | ~150–200 МБ | ✅ доступен |
| `false` | ~5–10 МБ | ❌ недоступен |


## Параметр duration_seconds
```yaml
duration_seconds: 12.0    # Быстрая генерация, короткие записи
duration_seconds: 300.0   # Реалистичная длительность (5 мин), медленная генерация
```
- 12 сек — достаточно для расчёта RMSSD/SDNN, быстрая генерация
- 300 сек (5 мин) — стандарт для HRV-анализа, генерация 3000 записей займёт 5–10 минут

## Полный пример: команда с разнообразием
```yaml
settings:
  duration_seconds: 12.0
  db_path: null
  store_raw_data: true
  seed: 42

team:
  # Подростки (12–14 лет) — высокая вариабельность
  - { birth_year: 2012, gender: M, profile: regular_mwf_morning }
  - { birth_year: 2011, gender: F, profile: regular_mwf_morning }
  - { birth_year: 2013, gender: M, profile: regular_mwf_morning }
  
  # Юниоры (15–17 лет) — средняя вариабельность
  - { birth_year: 2009, gender: M, profile: daily_evening }
  - { birth_year: 2008, gender: F, profile: daily_evening }
  
  # Взрослые (18–22 года) — умеренная вариабельность
  - { birth_year: 2005, gender: M, profile: regular_mwf_morning }
  - { birth_year: 2004, gender: F, profile: daily_evening }

profiles:
  regular_mwf_morning:
    days: [0, 2, 4]
    hour: 9
    minute: 0
    
  daily_evening:
    days: [0, 1, 2, 3, 4, 5, 6]
    hour: 18
    minute: 30
```
После сохранения запустите:
```bash
cd src/scripts
python prepare_database.py
```