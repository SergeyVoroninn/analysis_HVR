"""Единый каркас модальных окон приложения.

Собирает в одном месте boilerplate диалогов: заголовок/размер, модальность,
жизненный цикл (слежение за родителем, безопасное закрытие), фокус, доступ
к БД и единую стилизацию кнопок по семантическим ролям.
"""
from contextlib import contextmanager

import customtkinter as ctk
import tkinter as tk

from models import get_session
from theme import COL_NEUTRAL, COL_CRIT, COL_DANGER_HOVER

# --- Семантические роли кнопок (стиль задаётся в одном месте) ---
PRIMARY = "primary"   # главное действие (Сохранить/Применить) — цвет по умолчанию
CANCEL = "cancel"     # Отмена/Закрыть — нейтральный серый
DANGER = "danger"     # Удаление — красный

_ROLE_STYLE = {
    PRIMARY: (None, None),
    CANCEL: (COL_NEUTRAL, None),
    DANGER: (COL_CRIT, COL_DANGER_HOVER),
}


class BaseDialog(ctk.CTkToplevel):
    """Базовый каркас диалога.

    Подклассы вызывают super().__init__(parent, title=..., db_path=..., ...),
    затем строят содержимое и, при необходимости, self.result.
    """

    PARENT_POLL_MS = 200  # период проверки существования родительского окна

    def __init__(self, parent, *, title, db_path=None,
                 size=None, resizable=(False, False), modal=True):
        super().__init__(parent)
        self.db_path = db_path
        self.result = None
        self.title(title)
        if size:
            self.geometry(size)
        self.resizable(*resizable)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._modal = modal
        self._grab_owner = None
        if modal:
            # Запоминаем текущего владельца grab (если есть), чтобы восстановить
            # его при закрытии — корректная вложенная модальность.
            self._grab_owner = self._grab_current()
            self.grab_set()
            # Уведомляем ГЛАВНОЕ окно приложения: открылось модальное окно.
            # Слушатели (графики) скрывают свои всплывающие подсказки, чтобы
            # те не «зависали» поверх модального окна.
            try:
                parent_tl = self.master.winfo_toplevel()
                parent_tl.event_generate("<<ModalOpened>>")
            except Exception:
                pass

        self._parent_watch = None
        self._start_parent_watch()

    # ------------------------------------------------------------------
    # Жизненный цикл окна
    # ------------------------------------------------------------------
    def close(self):
        """Безопасно закрывает окно (отменяет таймер и уничтожает)."""
        self._stop_parent_watch()
        self._release_grab_and_restore()
        try:
            self.destroy()
        except Exception:
            pass

    def _release_grab_and_restore(self):
        """Снимает собственный grab и возвращает фокус владельцу (для вложенных)."""
        if not self._modal:
            return
        try:
            self.grab_release()
        except Exception:
            pass
        owner = self._grab_owner
        if owner is not None:
            try:
                if owner.winfo_exists():
                    owner.grab_set()
            except Exception:
                pass

    @staticmethod
    def _grab_current():
        """Возвращает текущее окно, владеющее grab, либо None."""
        try:
            return tk._default_root.grab_current() if tk._default_root else None
        except Exception:
            return None

    def _start_parent_watch(self):
        self._stop_parent_watch()
        self._parent_watch = self.after(self.PARENT_POLL_MS, self._check_parent)

    def _stop_parent_watch(self):
        if self._parent_watch is not None:
            try:
                self.after_cancel(self._parent_watch)
            except Exception:
                pass
            self._parent_watch = None

    def _check_parent(self):
        """Закрывает диалог, если родительское окно уничтожено."""
        try:
            if not self.master.winfo_exists():
                self.close()
                return
        except Exception:
            self.close()
            return
        self._parent_watch = self.after(self.PARENT_POLL_MS, self._check_parent)

    def _bring_to_front(self):
        """Поднимает окно поверх других и даёт фокус."""
        try:
            if self.winfo_exists():
                self.lift()
                self.focus_force()
        except Exception:
            pass

    def _center_over_parent(self, dy_factor=3):
        """Центрирует окно относительно родителя (по горизонтали и на ~1/3 по высоте)."""
        try:
            parent = self.master
            if not parent or not parent.winfo_exists():
                return
            self.update_idletasks()
            w, h = self.winfo_reqwidth(), self.winfo_reqheight()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw = parent.winfo_width() or parent.winfo_reqwidth()
            ph = parent.winfo_height() or parent.winfo_reqheight()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // dy_factor)
            self.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Доступ к БД
    # ------------------------------------------------------------------
    @contextmanager
    def _session(self):
        """Открывает сессию БД и гарантированно закрывает её."""
        session = get_session(self.db_path)
        try:
            yield session
        finally:
            session.close()

    def modal_loop(self):
        """Блокирует поток до закрытия диалога и возвращает self.result."""
        self.wait_window(self)
        return self.result

    # ------------------------------------------------------------------
    # Единая стилизация кнопок
    # ------------------------------------------------------------------
    def make_button(self, parent, text, command, kind=PRIMARY, *,
                    width=None, state="normal", side="left", padx=4, pady=0,
                    tooltip=None):
        """Создаёт кнопку с цветом по семантической роли (kind).

        Параметр `tooltip` добавляет всплывающую подсказку при наведении.
        """
        fg, hover = _ROLE_STYLE.get(kind, (None, None))
        kwargs = dict(text=text, command=command, state=state,
                      fg_color=fg, hover_color=hover)
        if width is not None:
            kwargs["width"] = width
        btn = ctk.CTkButton(parent, **kwargs)
        btn.pack(side=side, padx=padx, pady=pady)
        if tooltip:
            from .common import ToolTip
            ToolTip(btn, tooltip)
        return btn

    def make_button_bar(self, parent, pady=6):
        """Создаёт единую кнопочную строку (прозрачный frame)."""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(pady=pady)
        return bar