# analysis_HVR
## Стартап датчики контроля состояния спортсмена

Для запуска проекта нужны 6 внешних библиотек. Всё остальное (os, sys, sqlite3, datetime, uuid, random, math) входит в стандартную библиотеку Python.
### Основные зависимости
| Библиотека | Для чего |
| --- | --- |
| customtkinter | GUI приложения (app.py, dialogs.py) |
| matplotlib | Графики TP и стресса |
| tkcalendar | Виджет календаря для ввода даты рождения |
| sqlalchemy | ORM для работы с БД (models.py) |
| pyyaml | Чтение config.yaml и ecg_profiles.yaml |
| numpy | Анализ сигнала ЭКГ и RR-интервалов |

### 🛠 Опциональные для разработки
Эти библиотеки не нужны конечному пользователю, но используются при разработке:
| Библиотека | Назначение | Установка |
| --- | --- | --- |
| `pytest` | Автотесты  | `pip install pytest` |
| `pyinstaller` | Сборка в `AnalysisHVR.exe` | `pip install pyinstaller` |
| `pillow` | Прозрачный фон логотипа в заставке (необязательно) | `pip install pillow` |


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

## Настрока профиля ЭКГ

Файл src/scripts/ecg_profiles.yaml управляет качеством генерируемых ЭКГ-сигналов. Разные профили подходят для разных задач: отладка, точный анализ или быстрая генерация.

### 🏗️ Структура файла

```yaml
active_profile: default          # ← какой профиль используется сейчас

profiles:
  default:                       # название профиля
    description: ...             # описание
    transient_duration: 146      # переходный процесс
    baseline_mean: -200          # базовая линия
    baseline_noise_range: [-8, 8]# шум
    # ... параметры волн P, Q, R, S, T
    target:                      # целевые метрики качества
      min_snr: 15.0
      max_artifact_pct: 2.0
      max_baseline_drift: 50.0
```

### 🔧 Основные параметры

Переходный процесс (transient)
| Параметр | Описание | Влияние |
| --- | --- | --- |
| `transient_duration` | Длительность переходного процесса (отсчёты) | Сколько отсчётов в начале файла «настраивается» датчик |
| `transient_start_value` | Начальное значение | Чем больше, тем сильнее «всплеск» в начале |
| `transient_end_value` | Конечное значение | Куда приходит сигнал после переходного процесса |
Рекомендация: 100–150 отсчётов достаточно. Меньше = быстрее стабилизация.

### Базовая линия и шум
| Параметр | Описание | Влияние на качество |
| --- | --- | --- |
| `baseline_mean` | Среднее значение базовой линии | Сдвиг всего сигнала вверх/вниз |
| `baseline_respiratory_amplitude` | Амплитуда дыхательного дрейфа | Больше = сильнее «качание» базовой линии |
| `baseline_respiratory_frequency` | Частота дыхания (0.04–0.06 Гц) | Определяет скорость колебаний |
| `baseline_noise_range` | Диапазон шума [min, max] | Больше = ниже SNR, но реалистичнее |

#### Пример:
```yaml
baseline_noise_range:
  - -8
  - 8
```
Шум от -8 до +8 мкВ. [0, 0] = идеально чистый сигнал.

Расчёт:

```txt
heart_rate_period = 130 * RR_мс / 1000

Пример: RR 900 мс → 130 * 900 / 1000 = 117 отсчётов
```
Рекомендация: 110–120 для покоя (65–75 уд/мин).

### Волны P, Q, R, S, T
Каждая волна описывается тремя параметрами:
```yaml
r_wave:
  start: 14        # начало (отсчёт от начала комплекса)
  end: 19          # конец
  amplitude: 1300  # амплитуда (мкВ)
```

| Волна | Типичная амплитуда | Назначение |
| --- | --- | --- |
| P | 100–200 | Деполяризация предсердий |
| Q | -100 до -200 | Начало деполяризации желудочков |
| R | 800–1500 | Основной пик (используется для детекции) |
| S | -1000 до -1500 | Завершение деполяризации |
| T | 300–500 | Реполяризация желудочков |

Важно: R-пик должен быть самым высоким — детектор R-пиков ищет максимум.

### Целевые метрики качества (target)
```yaml
target:
  min_snr: 15.0              # минимальный SNR (дБ)
  max_artifact_pct: 2.0      # максимум артефактов (%)
  max_baseline_drift: 50.0   # максимум дрейфа базовой линии
```

| Метрика | Что измеряет | Хорошее значение |
| --- | --- | --- |
| `min_snr` | Отношение сигнал/шум | ≥15 дБ |
| `max_artifact_pct` | Процент артефактных R‑пиков | ≤2% |
| `max_baseline_drift` | Амплитуда дрейфа базовой линии | ≤50 |

### 📊 Сравнение трёх профилей
| Параметр | default | high_quality | fast | Назначение |
| --- | --- | --- | --- | --- |
| transient_duration | 146 | 100 | 80 | Баланс качества и скорости |
| baseline_noise_range | [-8, 8] | [0, 0] | [-20, 20] | Точный анализ ВРС |
| baseline_respiratory_amplitude | 92 | 41 | 60 | Быстрая отладка |
| R‑амплитуда | 1300 | 9283 | 1200 |  |
| min_snr | 15.0 | 20.0 | 12.0 |  |
| max_artifact_pct | 2.0 | 1.0 | 3.0 |  |
| Время генерации | 1× | 1× | ~0.8× |  |
| Качество | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |  |

### 🎯 Когда какой профиль использовать
default — универсальный выбор
```yaml
active_profile: default
```
```txt
Применение:
Разработка и тестирование GUI
Демонстрация приложения
Генерация тестовой базы для отчётов
Характеристики:
SNR ~15 дБ — реалистичный шум
Артефакты ~0.2% — почти идеально
Дрейф ~42 — в пределах нормы
```
high_quality — точный анализ
```yaml
active_profile: high_quality
```
```txt
Применение:
Научные исследования
Валидация алгоритмов анализа
Эталонные данные для сравнения
Особенности:
baseline_noise_range: [0, 0] — нет шума вообще
R-амплитуда 9283 — очень чёткие пики
Дрейф 30 — минимальный
Предупреждение: нереалистично «чистый» сигнал, не подходит для имитации реальных условий.
```
fast — быстрая генерация
```yaml
active_profile: fast
```
```txt
Применение:
Отладка пайплайна обработки
Быстрая проверка импорта/экспорта
CI/CD тесты
Особенности:
Шум [-20, 20] — больше шума, ниже SNR
Быстрее на ~20% за счёт короткого transient
Допускает больше артефактов (3%)
```
### 🚀 Переключение профилей
#### Шаг 1 — Измените active_profile в ecg_profiles.yaml
```txt
active_profile: high_quality    # или default, или fast
```
#### Шаг 2 — Перегенерируйте базу
```bash
cd src/scripts
python prepare_database.py
```
#### Шаг 3 — Проверьте качество
```bash
python ecg_generator.py
```
Выведет SNR, артефакты, дрейф и итоговый score в процентах.
### 🔬 Создание своего профиля
#### Пример: «Реалистичный с артефактами»
Добавьте в ecg_profiles.yaml:
```yaml
profiles:
  realistic:
    description: Реалистичный сигнал с умеренным шумом
    transient_duration: 120
    transient_start_value: 10000
    transient_end_value: -150
    baseline_mean: -200
    baseline_respiratory_amplitude: 100
    baseline_respiratory_frequency: 0.05
    baseline_noise_range:
      - -15
      - 15
    heart_rate_period: 115
    p_wave:
      start: 0
      end: 8
      amplitude: 150
    q_wave:
      start: 10
      end: 14
      amplitude: -150
    r_wave:
      start: 14
      end: 19
      amplitude: 1300
    s_wave:
      start: 19
      end: 25
      amplitude: -1400
    t_wave:
      start: 35
      end: 55
      amplitude: 350
    target:
      min_snr: 12.0
      max_artifact_pct: 5.0
      max_baseline_drift: 70.0
```
Активируйте:
```yaml
active_profile: realistic
```

### 🛠️ Калибровка профиля
Если метрики не соответствуют целевым, запустите автокалибровку:
```bash
cd src/scripts

# Калибровка одного профиля
python calibrate_ecg.py --profile default

# Калибровка всех профилей
python calibrate_ecg.py --all
```
Скрипт подберёт оптимальные параметры и перезапишет ecg_profiles.yaml.
### 💡 Советы по настройке
| Задача | Решение |
| --- | --- |
| Слишком много шума | Уменьшите `baseline_noise_range`: `[-5, 5]` вместо `[-15, 15]` |
| R‑пики не детектируются | Увеличьте `r_wave.amplitude` до 1500+ |
| Дрейф базовой линии | Уменьшите `baseline_respiratory_amplitude` до 40–60 |
| Нужна быстрая генерация | Используйте профиль `fast` или уменьшите `transient_duration` |
| Нужен идеальный сигнал | Используйте `high_quality` с `baseline_noise_range: [0, 0]` |
| Реалистичные условия | Добавьте шум `[-10, 10]` и дрейф 80–100 |

### ⚠️ Типовые ошибки
| Ошибка | Причина | Решение |
| --- | --- | --- |
| SNR < 10 дБ | Слишком большой шум или маленькая R‑амплитуда | Увеличьте `r_wave.amplitude` или уменьшите шум |
| Артефакты > 5% | R‑пики плохо выделяются | Увеличьте R‑амплитуду относительно шума |
| Дрейф > 80 | Слишком сильное дыхание | Уменьшите `baseline_respiratory_amplitude` |
| Детектор пропускает R‑пики | R‑амплитуда меньше шума | Увеличьте R до 1500+, шум до `[-10, 10]` |

### 📐 Полный шаблон профиля
```yaml
my_profile:
  description: Описание назначения профиля
  transient_duration: 120
  transient_start_value: 10000
  transient_end_value: -150
  baseline_mean: -200
  baseline_respiratory_amplitude: 80
  baseline_respiratory_frequency: 0.05
  baseline_noise_range:
    - -10
    - 10
  heart_rate_period: 115
  p_wave:
    start: 0
    end: 8
    amplitude: 150
  q_wave:
    start: 10
    end: 14
    amplitude: -150
  r_wave:
    start: 14
    end: 19
    amplitude: 1300
  s_wave:
    start: 19
    end: 25
    amplitude: -1400
  t_wave:
    start: 35
    end: 55
    amplitude: 350
  target:
    min_snr: 15.0
    max_artifact_pct: 2.0
    max_baseline_drift: 50.0
```
Теперь вы можете гибко настраивать качество генерируемых ЭКГ под любую задачу — от быстрой отладки до научных исследований.

## Ручной чек‑лист (GUI)

Прогоните после крупных правок — 2 минуты.

| № | Действие | Ожидаемый результат |
|---|----------|---------------------|
| 1 | `python app.py` | Заставка → окно без пауз и ошибок в консоли |
| 2 | Выбрать спортсмена | Отображаются детали, heatmap и графики |
| 3 | ◀ / ▶ год | Год переключается в диапазоне доступных данных |
| 4 | Клик по году на heatmap | Появляется рамка недели + отображаются недельные графики |
| 5 | Клик по оранжевому столбику ИС | Выделяется та же неделя (проверка `align='edge'`) |
| 6 | Клик по зелёному квадрату недели | Открывается окно со списком ЭКГ за 3 часа |
| 7 | Клик по серому квадрату | Ничего не происходит |
| 8 | Экспорт записи | Файл `.teamloggerh10` сохраняется |
| 9 | Удалить запись | Heatmap и графики обновляются |
| 10 | ＋ спортсмен | Открывается календарь (формат ДД‑ММ‑ГГГГ), данные сохраняются |
| 11 | ✎ / 🗑 спортсмена | Выполняется редактирование / каскадное удаление |
| 12 | Импорт файла | Происходит привязка по `polar_id`, дубликаты блокируются |
| 13 | Закрыть окно | Процесс завершается, нет «висячего» `python.exe` |

## Структура автотестов

```text
src/
├── tests/
│   ├── conftest.py          # пути и фикстуры
│   ├── test_analysis.py     # метрики ВРС
│   ├── test_ecg_generator.py# согласованность ECG↔RR
│   ├── test_database.py     # ORM CRUD + каскады
│   └── test_app_gui.py      # смоук-тест GUI
```

## Установка pytest
```bash
pip install pytest
```

## Запуск
```bash
cd C:\s21\projects\analysis_HVR\src

python -m pytest tests -v              # все тесты
python -m pytest tests/test_analysis.py -v   # один файл
python -m pytest tests -k consistency -v     # по имени
```

# 📦 Создание EXE-файла приложения
Используем PyInstaller — он соберёт Python + все библиотеки + данные в один исполняемый файл.


## Установка PyInstaller
В exe-версии база данных должна лежать рядом с exe, а не внутри архива. 
```bash
pip install pyinstaller
```
## Запуск сборки:
```bash
cd \analysis_HVR\src
build.bat
```
## Что означают флаги
| Флаг | Назначение |
| --- | --- |
| `--onedir` | Папка с exe + файлами (быстрый старт, проще отлаживать) |
| `--windowed` | Без чёрного окна консоли |
| `--add-data "logo21.png;."` | Логотип внутрь сборки |
| `--add-data "scripts\ecg_profiles.yaml;."` | Профили ЭКГ внутрь сборки |
| `--collect-all customtkinter` | Темы и шрифты customtkinter |
| `--hidden-import ...` | Модули, которые PyInstaller не нашёл сам |



## Результат
```txt
dist/
└── AnalysisHVR/
    ├── AnalysisHVR.exe      ← запуск
    ├── _internal/           ← библиотеки и данные
    └── data/
        └── ecg.db           ← база данных
```

## Раздача пользователям
```bah
cd dist
tar -a -cf AnalysisHVR.zip AnalysisHVR
```




