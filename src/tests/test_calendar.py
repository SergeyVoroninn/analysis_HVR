"""
Комплексные тесты календаря (tkcalendar).
Проверяют базовые операции и устойчивость GUI при смене месяца/года.
"""
import datetime
import os
import sys
import time
import tkinter as tk

PROJECT_DIR = r"C:\s21\projects\analysis_HVR\src"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from dialogs import _ForegroundDateEntry


def find_widget_by_text(parent, text_contains):
    """Рекурсивный поиск виджета по части текста."""
    try:
        if hasattr(parent, 'cget') and parent.cget('text'):
            widget_text = str(parent.cget('text'))
            if text_contains.lower() in widget_text.lower():
                return parent
    except Exception:
        pass
    
    for child in parent.winfo_children():
        result = find_widget_by_text(child, text_contains)
        if result:
            return result
    return None


# ==============================================================================
# ТЕСТ 1: Базовые операции (дата, открытие, закрытие)
# ==============================================================================
def test_calendar_basic_operations():
    """Проверяет программную смену даты и корректное открытие/закрытие."""
    root = tk.Tk()
    root.withdraw()

    try:
        cal = _ForegroundDateEntry(
            root, width=12, date_pattern='dd-mm-yyyy',
            year=2023, month=6, day=15,
            locale="ru_RU"
        )
        cal.pack(padx=20, pady=20)
        root.update_idletasks()

        # 1. Начальная дата
        assert cal.get_date() == datetime.date(2023, 6, 15)
        
        # 2. Программная смена даты
        cal.set_date(datetime.date(2024, 12, 31))
        root.update_idletasks()
        assert cal.get_date() == datetime.date(2024, 12, 31)

        # 3. Открытие и проверка существования виджетов
        cal.drop_down()
        root.update_idletasks()
        assert cal._top_cal.winfo_exists()
        assert cal._calendar.winfo_exists()

        # 4. Корректное закрытие (не через destroy!)
        if hasattr(cal, '_close_calendar'):
            cal._close_calendar()
        else:
            cal._top_cal.withdraw()
        root.update_idletasks()

        # 5. Повторное открытие
        cal.drop_down()
        root.update_idletasks()
        assert cal._top_cal.winfo_exists()
        assert cal._calendar.winfo_exists()

    finally:
        try:
            if hasattr(cal, '_top_cal') and cal._top_cal.winfo_exists():
                cal._top_cal.destroy()
        except Exception:
            pass
        root.destroy()


# ==============================================================================
# ТЕСТ 2: Интеграционный тест смены месяца через GUI
# ==============================================================================
def test_calendar_month_selection_gui():
    """Проверяет, что календарь не пропадает при клике на заголовок месяца."""
    root = tk.Tk()
    root.title("Calendar GUI Test")
    root.geometry("400x300+100+100")
    root.update_idletasks()

    try:
        cal = _ForegroundDateEntry(
            root, width=12, date_pattern='dd-mm-yyyy',
            year=2023, month=6, day=15,
            locale="ru_RU"
        )
        cal.pack(padx=20, pady=20)
        root.update_idletasks()

        # 1. Открываем календарь
        cal.drop_down()
        root.update_idletasks()
        time.sleep(0.1)
        root.update()
        assert cal._top_cal.winfo_ismapped(), "Календарь должен быть виден"

        # 2. Ищем заголовок месяца
        header = None
        for child in cal._calendar.winfo_children():
            try:
                text = child.cget('text')
                if text and ('2023' in text or 'июн' in text.lower()):
                    header = child
                    break
            except Exception:
                continue
        
        if not header:
            header = cal._calendar # Fallback на координатный клик

        # 3. Кликаем по заголовку (открывается выбор месяца)
        header.event_generate('<Button-1>', x=50, y=10)
        root.update_idletasks()
        time.sleep(0.2) # Ждём перестройки виджетов
        root.update()
        
        # КЛЮЧЕВАЯ ПРОВЕРКА: окно не должно исчезнуть
        assert cal._top_cal.winfo_ismapped(), "Календарь исчез после клика на заголовок!"
        assert cal._top_cal.winfo_exists(), "Окно календаря уничтожено!"

        # 4. Пытаемся выбрать другой месяц
        month_selected = False
        for child in cal._calendar.winfo_children():
            try:
                text = child.cget('text')
                if text and text.lower() in ['янв', 'фев', 'мар', 'апр', 'май', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']:
                    child.event_generate('<Button-1>')
                    root.update_idletasks()
                    time.sleep(0.1)
                    root.update()
                    month_selected = True
                    break
            except Exception:
                continue

        # 5. Проверяем финальное состояние
        current_date = cal.get_date()
        assert isinstance(current_date, datetime.date), "Дата должна быть валидным объектом date"

    finally:
        try:
            if hasattr(cal, '_top_cal') and cal._top_cal.winfo_exists():
                if hasattr(cal, '_close_calendar'):
                    cal._close_calendar()
                else:
                    cal._top_cal.destroy()
        except Exception:
            pass
        root.destroy()