"""
ghost.py — базовый класс виджетов с «призрачным» ресайзом.

Пока зажата кнопка мыши (тянем границу окна) вместо перерисовки
содержимого рисуются белые рамки; при отпускании кнопки содержимое
пересобирается под новый размер ровно один раз.

Наследник реализует три метода:
  target_size(avail_w) -> (w, h)              желаемый размер содержимого;
  ghost_rects(w, h)    -> [(x1, y1, x2, y2)]  рамки для отрисовки;
  apply_size(w, h)                            реальная пересборка.
"""
import tkinter as tk

from theme import COL_BG_DARK

SETTLE_MS = 200


class GhostResizeFrame(tk.Frame):
    def __init__(self, master, **kw):
        kw.setdefault("bg", COL_BG_DARK)
        super().__init__(master, **kw)
        self._bg = kw["bg"]

        # оверлей — ребёнок РОДИТЕЛЯ: не обрезается нашим фреймом
        # и рисуется поверх содержимого
        self._overlay = tk.Canvas(self.master, bg=self._bg, highlightthickness=0)
        self._overlay_placed = False
        self._rect_items = []
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
        if (w, h) == self._cur:
            return                                # размер не менялся

        if not self._mouse_held():                 # не тянем: применяем сразу
            self._cancel_timer()
            self._hide_ghost()
            self._cur = (w, h)
            self.apply_size(w, h)
            return

        # тянем границу: белые рамки до отпускания кнопки
        self._show_ghost(w, h)
        self._restart_timer()

    def _on_timer(self):
        self._timer = None
        if self._mouse_held():                     # всё ещё тянем — ждём
            self._timer = self.after(SETTLE_MS, self._on_timer)
            return
        self._hide_ghost()
        avail = self.winfo_width()
        if avail < 100:
            return
        w, h = self.target_size(avail)
        if self._cur != (w, h):
            self._cur = (w, h)
            self.apply_size(w, h)

    # ---------------- ghost-отрисовка ----------------
    def _show_ghost(self, w, h):
        x, y = self.winfo_x(), self.winfo_y()
        if self._overlay_placed:
            self._overlay.place_configure(x=x, y=y, width=w, height=h)
        else:
            self._overlay.place(x=x, y=y, width=w, height=h)
            self._overlay_placed = True
        self._overlay.tk.call('raise', self._overlay._w)

        rects = self.ghost_rects(w, h)
        # переиспользуем созданные рамки, меняем только координаты
        for i, (x1, y1, x2, y2) in enumerate(rects):
            if i < len(self._rect_items):
                self._overlay.coords(self._rect_items[i], x1, y1, x2, y2)
            else:
                self._rect_items.append(
                    self._overlay.create_rectangle(x1, y1, x2, y2,
                                                   outline="white",
                                                   tags="ghost"))
        for extra in self._rect_items[len(rects):]:
            self._overlay.delete(extra)
        del self._rect_items[len(rects):]

    def _hide_ghost(self):
        self._overlay.place_forget()
        self._overlay_placed = False
        self._overlay.delete("ghost")
        self._rect_items = []

    # ---------------- таймер ----------------
    def _restart_timer(self):
        if self._timer:
            self.after_cancel(self._timer)
        self._timer = self.after(SETTLE_MS, self._on_timer)

    def _cancel_timer(self):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None

    @staticmethod
    def _mouse_held():
        """Зажата ли левая кнопка мыши прямо сейчас (Windows)."""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False
