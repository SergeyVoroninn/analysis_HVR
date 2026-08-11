"""
Заставка — CTkToplevel поверх скрытого корневого окна.
Один интерпретатор Tcl = нет мигания и Tcl-ошибок.
"""
import os
import customtkinter as ctk
import tkinter as tk

from theme import COL_BG_DARK, COL_TEXT_LIGHT, COL_ACCENT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class SplashScreen(ctk.CTkToplevel):
    WIDTH = 420
    HEIGHT = 260

    def __init__(self, master, show_ms=1500, on_close=None, auto_close=True):
        super().__init__(master)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # Подавляем любые Tcl-ошибки от таймеров
        self.report_callback_exception = lambda *args: None

        self.on_close = on_close
        self.show_ms = show_ms
        self._after_ids = []

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{(sw-self.WIDTH)//2}+{(sh-self.HEIGHT)//2}")
        self.configure(fg_color=COL_BG_DARK)

        self._load_corner_logo()

        self.logo = tk.Canvas(self, width=80, height=80,
                              bg=COL_BG_DARK, highlightthickness=0)
        self.logo.pack(pady=(40, 10))
        self.logo.create_oval(5, 5, 75, 75, fill=COL_ACCENT, outline="")
        self.logo.create_line(20, 40, 30, 40, 35, 25, 42, 55, 49, 40, 60, 40,
                              fill="white", width=3, smooth=True)

        ctk.CTkLabel(self, text="Анализ ВРС",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COL_TEXT_LIGHT).pack(pady=(0, 4))
        ctk.CTkLabel(self, text="Система мониторинга состояния спортсменов",
                     font=ctk.CTkFont(size=11),
                     text_color="#9a9a9a").pack(pady=(0, 20))

        self.progress = ctk.CTkProgressBar(self, width=280, height=6)
        self.progress.pack(pady=(0, 10))
        self.progress.set(0)

        ctk.CTkLabel(self, text="v1.0", font=ctk.CTkFont(size=9),
                     text_color="#666666").pack(side="bottom", pady=10)

        self._animate_progress()
        if auto_close:
            self._after_ids.append(self.after(self.show_ms, self._close))

    def _load_corner_logo(self):
        logo_path = os.path.join(BASE_DIR, "logo21.png")
        if not os.path.exists(logo_path):
            return
        try:
            img = tk.PhotoImage(file=logo_path)
            img = img.subsample(max(1, img.width() // 90))
            self._corner_logo = img
            tk.Label(self, image=img, bg=COL_BG_DARK, bd=0,
                     highlightthickness=0).place(relx=1.0, rely=0.0,
                                                 anchor="ne", x=-12, y=12)
        except Exception:
            pass

    def _animate_progress(self, step=0):
        steps = 40
        phase = step % (2 * steps)
        v = phase / steps if phase < steps else 2 - phase / steps
        try:
            self.progress.set(v)
        except Exception:
            return
        self._after_ids.append(
            self.after(40, lambda: self._animate_progress(step + 1)))

    def close_splash(self):
        self._close()

    def _close(self):
        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_close:
            self.on_close()