"""
ghost.py — базовый класс виджетов с «призрачным» ресайзом.

Во время перетаскивания границы окна вместо перерисовки содержимого
показываются белые рамки; когда кнопка мыши отпущена — содержимое
пересобирается под новый размер ровно один раз.

Наследник реализует три метода:
  target_size(avail_w) -> (w, h)              желаемый размер содержимого;
  ghost_rects(w, h)    -> [(x1, y1, x2, y2)]  рамки для отрисовки;
  apply_size(w, h)                            реальная пересборка.
"""
import tkinter as tk

from theme import COL_BG_DARK


class GhostResizeFrame(tk.Frame):
    def __init__(self, master, **kw):
        kw.setdefault("bg", COL_BG_DARK)
        super().__init__(master, **kw)
        self._bg = kw["bg"]

        # оверлей — ребёнок РОДИТЕЛЯ: не обрезается нашим фреймом
        # и рисуется поверх содержимого
        self._overlay = tk.Canvas(self.master, bg=self._bg, highlightthickness=0)
        self._cur = None
        self._timer = None
        self.bind("<Configure>", self._on_configure)

    # ---------------- переопределяются наследником ----------------
    def target_size(self, avail_w):
        return avail_w, self.winfo_height()

    def ghost_rects(self, w, h):
        return [(1, 1, w - 1, h - 1)]

    def apply_size(self, w, h):
        pass

    # ---------------- логика ресайза ----------------
    def _on_configure(self, event):
        avail = self.winfo_width()
        if avail < 100:
            return
        w, h = self.target_size(avail)

        if self._cur is None:                      # первый замер — без призрака
            self._cur = (w, h)
            self.apply_size(w, h)
            return

        if (w, h) == self._cur and self._timer is None:
            return                                 # размер не менялся

        if not self._mouse_held():
            # мышь не зажата: максимизация / финальный settle —
            # применяем сразу и гасим ожидающую финализацию
            if self._timer:
                self.after_cancel(self._timer)
                self._timer = None
            if self._cur != (w, h):
                self._cur = (w, h)
                self.apply_size(w, h)
            return

        # мышь зажата: белые рамки до отпускания
        self._show_ghost(w, h)
        if self._timer:
            self.after_cancel(self._timer)
        self._timer = self.after(100, self._finalize, w, h)

    def _show_ghost(self, w, h):
        self._overlay.place(x=self.winfo_x(), y=self.winfo_y(),
                            width=w, height=h)
        self._overlay.tk.call('raise', self._overlay._w)
        self._overlay.delete("ghost")
        for x1, y1, x2, y2 in self.ghost_rects(w, h):
            self._overlay.create_rectangle(x1, y1, x2, y2,
                                           outline="white", tags="ghost")

    def _finalize(self, w, h):
        self._timer = None
        if self._mouse_held():                     # всё ещё тянут — ждём
            self._timer = self.after(100, self._finalize, w, h)
            return

        self._overlay.delete("ghost")
        self._overlay.place_forget()

        # пересчитываем ТЕКУЩИЙ целевой размер вместо захваченного ранее
        avail = self.winfo_width()
        if avail < 100:
            return
        w2, h2 = self.target_size(avail)
        if self._cur != (w2, h2):                  # и только если он новый
            self._cur = (w2, h2)
            self.apply_size(w2, h2)

    @staticmethod
    def _mouse_held():
        """Зажата ли левая кнопка мыши прямо сейчас (Windows)."""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False