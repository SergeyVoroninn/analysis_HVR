"""Диалог просмотра/редактирования комментария к метрике за дату."""
import datetime
import customtkinter as ctk
from tkinter import scrolledtext

from .base import BaseDialog, CANCEL, PRIMARY, DANGER
from metric_comments import upsert_comment, get_comment


class CommentDialog(BaseDialog):
    """Просмотр/редактирование комментария к (метрика, дата).

    Показывает существующий комментарий (если был) в редактируемом поле.
    «Сохранить» — сохраняет/обновляет, «Удалить» — удаляет запись.
    результат: "save" | "delete" | None.
    """

    def __init__(self, parent, *, athlete_id, metric_key, metric_name,
                 comment_date, db_path=None):
        super().__init__(parent, title="Комментарий",
                         db_path=db_path, size="480x320", modal=True)

        self.athlete_id = athlete_id
        self.metric_key = metric_key
        self.comment_date = comment_date

        if isinstance(comment_date, datetime.date):
            date_str = comment_date.strftime("%d.%m.%Y")
        else:
            date_str = str(comment_date)

        ctk.CTkLabel(self, text=f"{metric_name} · {date_str}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 4))

        self.text = scrolledtext.ScrolledText(
            self, wrap="word", height=8, padx=10, pady=10,
            font=("Segoe UI", 11), bg="#2d2d2d", fg="#cccccc",
            insertbackground="#cccccc")
        self.text.pack(fill="both", expand=True, padx=12, pady=4)

        existing = self._load_existing()
        if existing:
            self.text.insert("1.0", existing)

        bar = self.make_button_bar(self, pady=8)
        self.make_button(bar, "Сохранить", self._on_save, kind=PRIMARY,
                         tooltip="Сохранить комментарий")
        self.make_button(bar, "Удалить", self._on_delete, kind=DANGER,
                         tooltip="Удалить комментарий")
        self.make_button(bar, "Отмена", self.close, kind=CANCEL,
                         tooltip="Закрыть без изменений")

        self._center_over_parent()

    def _load_existing(self):
        try:
            return get_comment(self.db_path, self.athlete_id, self.metric_key,
                               self.comment_date)
        except Exception:
            return None

    def _on_save(self):
        text = self.text.get("1.0", "end").strip()
        try:
            upsert_comment(self.db_path, self.athlete_id, self.metric_key,
                           self.comment_date, text)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}", parent=self)
            return
        self.result = "save"
        self.close()

    def _on_delete(self):
        from metric_comments import delete_comment
        try:
            delete_comment(self.db_path, self.athlete_id, self.metric_key,
                           self.comment_date)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", f"Не удалось удалить:\n{e}", parent=self)
            return
        self.result = "delete"
        self.close()