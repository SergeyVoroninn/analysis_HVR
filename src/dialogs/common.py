"""Общие виджеты для диалогов."""
import tkinter as tk
import customtkinter as ctk
from tkcalendar import DateEntry

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_WEEKEND,
                   COL_ACCENT, COL_SELECTION, COL_TOOLTIP_BG)


class ToolTip:
    """Всплывающая подсказка «из старых программ».

    Показывается при наведении мыши на виджет с небольшой задержкой и
    исчезает при уходе курсора или клике.
    """

    def __init__(self, widget, text, delay_ms=400):
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._hide()
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + max(self.widget.winfo_height(), 8) + 4
            self._tip = tk.Toplevel(self.widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self._tip, text=self.text, justify="left",
                     bg=COL_TOOLTIP_BG, fg=COL_SELECTION,
                     relief="solid", borderwidth=1,
                     font=("Segoe UI", 9),
                     padx=6, pady=2).pack()
        except tk.TclError:
            self._tip = None

    def _hide(self, event=None):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def destroy(self):
        """Отвязать подсказку (лучше вызвать при освобождении виджета)."""
        self._hide()
        for seq in ("<Enter>", "<Leave>", "<ButtonPress>"):
            try:
                self.widget.unbind(seq)
            except Exception:
                pass


class _ForegroundDateEntry(DateEntry):
    """DateEntry, который не пропадает при смене месяца/года.

    Дополнительно поддерживает «пустую» дату: если рождение не задано,
    поле отображается пустым, а ``get_date`` возвращает None. Это нужно,
    чтобы дату рождения можно было оставлять незаполненной (по умолчанию),
    а не подставлять фиктивную дату вроде 01.01.2005.
    """

    def __init__(self, *args, **kwargs):
        self.required = kwargs.pop("required", True)
        super().__init__(*args, **kwargs)
        # В «необязательном» режиме поле стартует пустым, без фиктивной даты.
        if not self.required:
            self._clear_text()
        self._rebuild_lock = False  # Блокировка от рекурсии
        # tkcalendar инициализирует _downarrow_name асинхронно (через таймер),
        # а _on_motion по наведению мыши может сработать раньше -> AttributeError.
        # Ставим безопасное значение по умолчанию, чтобы не падало до его определения.
        if not hasattr(self, "_downarrow_name"):
            self._downarrow_name = "__none__"

    def _clear_text(self):
        """Очищает поле ввода (дата рождения не задана)."""
        self.delete(0, "end")

    def _validate_date(self):
        """Пустая необязательная дата — не подставляем форсированно дефолт."""
        if not self.required and not self.get().strip():
            return True
        return super()._validate_date()

    def get_date(self):
        """Возвращает дату или None, если поле пустое и не обязательное."""
        if not self.required and not self.get().strip():
            return None
        return super().get_date()

    def drop_down(self):
        super().drop_down()
        self._ensure_foreground()

    def _ensure_foreground(self, event=None):
        """Возвращает календарь на передний план."""
        try:
            if not hasattr(self, '_top_cal') or not self._top_cal.winfo_exists():
                return

            # Поднимаем окно наверх
            self._top_cal.lift()
            self._top_cal.attributes("-topmost", True)
            self._top_cal.attributes("-topmost", False)
            self._top_cal.focus_force()

            # Отслеживаем перестройку календаря (смена месяца/года)
            if not self._rebuild_lock:
                self._top_cal.bind('<Configure>', self._on_calendar_rebuild, add='+')

        except Exception:
            pass

    def _on_calendar_rebuild(self, event=None):
        """Срабатывает после перестройки календаря."""
        if self._rebuild_lock:
            return
        try:
            self._rebuild_lock = True
            # Ждем завершения перестройки и возвращаем окно наверх
            self.master.after(50, self._ensure_foreground)
        finally:
            # Снимаем блокировку через 100 мс
            self.master.after(100, self._release_lock)

    def _release_lock(self):
        self._rebuild_lock = False