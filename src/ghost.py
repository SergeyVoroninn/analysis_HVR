"""
ghost.py — контроллер «призрачного» ресайза для блока виджетов.

Во время изменения ширины окна вместо перерисовки содержимого рисуются
белые рамки; после отпускания кнопки мыши содержимое пересобирается под
новый размер ровно один раз.

Управляемый блок (Heatmap, ChartsPanel) предоставляет методы:
  target_size(avail_w) -> (w, h)              желаемый размер содержимого;
  ghost_rects(w, h)    -> [(x1,y1,x2,y2)]     рамки в локальных координатах;
  apply_size(w, h)                             реальная пересборка;
  ghost_shown() / ghost_hidden()               (опционально) freeze/unfreeze.

Контроллер сам расставляет блоки по вертикали (place) и является
единственным источником правды: ресайз одного блока не дёргает соседей,
поэтому нет цепочки <Configure> → пересборка → <Configure>.
"""
import os
import time as _time

import tkinter as tk

from theme import COL_BG_DARK

DEBUG = os.environ.get("HVR_DEBUG") == "1"
_T0 = _time.time()


def _dbg(msg):
    if DEBUG:
        print(f"[{_time.time() - _T0:7.3f}] {msg}", flush=True)


SETTLE_MS = 150
POLL_MS = 40


class ResizeController:
    def __init__(self, master, blocks, gap=10, bg=COL_BG_DARK):
        self.master = master
        self.blocks = blocks
        self.gap = gap
        self._cur = None
        self._last_avail = None
        self._settle = None
        self._poll = None
        self._overlay = tk.Canvas(master, bg=bg, highlightthickness=0)
        self._overlay_placed = False
        self._rect_items = []
        master.bind("<Configure>", self._on_configure)

    # ---------------- вычисление ----------------
    def _compute(self, avail):
        return [b.target_size(avail) for b in self.blocks]

    def _positions(self, sizes):
        """Верхние Y-координаты блоков и общая высота колонки."""
        ys, y = [], 0
        for (w, h) in sizes:
            ys.append(y)
            y += h + self.gap
        return ys, max(0, y - self.gap)

    # ---------------- события ----------------
    def _on_configure(self, event):
        avail = self.master.winfo_width()
        if avail < 100:
            return
        _dbg(f"CONF avail={avail} mouse={self._mouse_held()} cur={self._cur}")
        if self._cur is not None and avail == self._last_avail:
            _dbg("CONF skip (width unchanged)")
            return
        self._last_avail = avail
        sizes = self._compute(avail)

        if self._cur is None:                      # первый замер
            self._cur = sizes
            _dbg(f"LAYOUT first {sizes}")
            self._layout(sizes)
            return
        if sizes == self._cur:
            _dbg("CONF sizes unchanged")
            return

        if self._mouse_held():
            # тянем границу: белые рамки, пересборка — после отпускания
            self._show_ghost(sizes)
            self._ensure_poll()
        else:
            # не тянем: склеиваем пачку <Configure> до «оседания»
            self._schedule_settle()

    # ---------------- применение ----------------
    def _layout(self, sizes):
        ys, total = self._positions(sizes)
        for b, (w, h), y in zip(self.blocks, sizes, ys):
            b.place(x=0, y=y)
            b.configure(width=w, height=h)
            b.apply_size(w, h)
        self.master.configure(height=total)
        _dbg(f"LAYOUT total_h={total}")

    def _do_apply(self):
        self._settle = None
        if self._mouse_held():
            _dbg("APPLY cancelled (mouse held)")
            return
        avail = self.master.winfo_width()
        if avail < 100:
            return
        sizes = self._compute(avail)
        if self._cur != sizes:
            self._cur = sizes
            _dbg(f"APPLY {sizes}")
            self._layout(sizes)
        self._hide_ghost()

    # ---------------- отложенная пересборка ----------------
    def _schedule_settle(self):
        if self._settle is not None:
            self.master.after_cancel(self._settle)
        self._settle = self.master.after(SETTLE_MS, self._do_apply)

    # ---------------- опрос «отпустили ли кнопку» ----------------
    def _ensure_poll(self):
        if self._poll is None:
            self._poll = self.master.after(POLL_MS, self._poll_release)

    def _poll_release(self):
        self._poll = None
        if self._mouse_held():
            self._ensure_poll()
            return
        self._schedule_settle()

    # ---------------- ghost-отрисовка ----------------
    def _show_ghost(self, sizes):
        ys, total = self._positions(sizes)
        avail = self.master.winfo_width()
        if self._overlay_placed:
            self._overlay.place_configure(x=0, y=0, width=avail, height=total)
        else:
            self._overlay.place(x=0, y=0, width=avail, height=total)
            self._overlay_placed = True
        self._overlay.tk.call('raise', self._overlay._w)
        self._overlay.delete("ghost")
        self._rect_items = []
        for b, (w, h), y in zip(self.blocks, sizes, ys):
            for x1, y1, x2, y2 in b.ghost_rects(w, h):
                self._rect_items.append(self._overlay.create_rectangle(
                    x1, y1 + y, x2, y2 + y, outline="white", tags="ghost"))
        for b in self.blocks:
            b.ghost_shown()
        _dbg(f"GHOST+ {sizes}")

    def _hide_ghost(self):
        if not self._overlay_placed:
            return
        _dbg("GHOST-")
        self._overlay.place_forget()
        self._overlay_placed = False
        self._overlay.delete("ghost")
        self._rect_items = []
        for b in self.blocks:
            b.ghost_hidden()

    @staticmethod
    def _mouse_held():
        """Зажата ли левая кнопка мыши прямо сейчас (Windows)."""
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False
