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
![Подготовка тестовых данных](images/prepare_database.png)
*Рисунок 1. Командная строка. Подготовка иестовых данных с помощью скрипта.*

![Главное окно приложения](images/app_main.png)
*Рисунок 2. Главное окно приложения анализа ВРС*
Кликайте по квадратам, чтобы выбрать неделю и просмотреть ЭКГ-записи.

![Главное окно приложения](images/athlet_edit.png)
*Рисунок 3. Окно редактирования добавления аилета*

![Главное окно приложения](images/app_import.png)
*Рисунок 4. Импорт файла записи с датчика*

![Главное окно приложения](images/ecg_list.png)
*Рисунок 5. Список записей в трехчасовой ячейке*


