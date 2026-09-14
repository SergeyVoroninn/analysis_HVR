"""
analysis_dialog.py — диалоговое окно для отображения детального анализа.
Без скроллинга, весь текст выводится сразу.
"""
import tkinter as tk
from theme import COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT


class AnalysisDialog(tk.Toplevel):
    """Модальное окно с детальным анализом метрики."""
    
    def __init__(self, parent, analysis, db_path=None):
        super().__init__(parent)
        self.title("📊 Детальный анализ ВСР")
        self.configure(bg=COL_BG_DARK)
        # Фиксированный комфортный размер, запрещающий изменение
        self.geometry("600x520")
        self.resizable(False, False)
        
        self.transient(parent)  # Модальное окно
        self.grab_set()  # Блокировка родительского окна
        
        # Центрируем окно относительно родителя
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 600) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 520) // 2
        self.geometry(f"+{x}+{y}")
        
        self.analysis = analysis
        self._create_widgets()
        
        # Закрытие по Escape
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()
    
    def _create_widgets(self):
        # 1. Заголовок
        header_frame = tk.Frame(self, bg=COL_BG_WIDGET)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        tk.Label(
            header_frame,
            text=f"📊 {self.analysis.athlete_name}",
            font=("Segoe UI", 14, "bold"),
            bg=COL_BG_WIDGET,
            fg=COL_TEXT_LIGHT
        ).pack(pady=(0, 5))
        
        tk.Label(
            header_frame,
            text=self.analysis.recorded_at.strftime("%d.%m.%Y %H:%M"),
            font=("Segoe UI", 10),
            bg=COL_BG_WIDGET,
            fg="#888"
        ).pack()
        
        # 2. Основной контент (простой Frame без Canvas и скролла)
        content_frame = tk.Frame(self, bg=COL_BG_DARK)
        content_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Секция: Показатели
        self._add_section(content_frame, "📈 Показатели ВСР", [
            (f"{self.analysis.tp_color} TP", f"{self.analysis.tp:.0f} мс² — {self.analysis.tp_status}"),
            (f"{self.analysis.stress_color} Стресс", f"{self.analysis.stress_si:.0f} у.е. — {self.analysis.stress_status}"),
            ("💓 ЧСС", f"{self.analysis.mean_hr:.0f} уд/мин"),
            ("📊 RMSSD", f"{self.analysis.rmssd:.0f} мс"),
            ("📊 SDNN", f"{self.analysis.sdnn:.0f} мс"),
        ])
        
        # Разделитель
        tk.Frame(content_frame, height=2, bg="#444").pack(fill="x", pady=10)
        
        # Секция: Рекомендация
        self._add_section(content_frame, "💡 Рекомендация", [
            ("", self.analysis.recommendation)
        ])
        
        # Секция: Детальный анализ (используем Label с переносом слов вместо Text)
        tk.Label(
            content_frame,
            text="📝 Детальный анализ:",
            font=("Segoe UI", 11, "bold"),
            bg=COL_BG_DARK,
            fg=COL_TEXT_LIGHT,
            anchor="w"
        ).pack(fill="x", padx=10, pady="10 5")
        
        tk.Label(
            content_frame,
            text=self.analysis.detailed_comment,
            font=("Segoe UI", 10),
            bg=COL_BG_WIDGET,
            fg=COL_TEXT_LIGHT,
            padx=15,
            pady=15,
            wraplength=550,      # Перенос длинных строк
            justify="left"       # Выравнивание по левому краю
        ).pack(fill="x", padx=10, pady=5)
        
        # 3. Кнопка закрытия
        btn_frame = tk.Frame(self, bg=COL_BG_DARK)
        btn_frame.pack(fill="x", pady=15)
        
        tk.Button(
            btn_frame,
            text="Закрыть (Esc)",
            command=self.destroy,
            bg="#4fc3f7",
            fg="#1e1e1e",
            font=("Segoe UI", 10, "bold"),
            padx=30,
            pady=8,
            relief="flat",
            cursor="hand2"
        ).pack()

    def _add_section(self, parent, title, items):
        """Добавляет секцию с заголовком и списком параметров."""
        tk.Label(
            parent,
            text=title,
            font=("Segoe UI", 11, "bold"),
            bg=COL_BG_DARK,
            fg=COL_TEXT_LIGHT,
            anchor="w"
        ).pack(fill="x", padx=10, pady="10 5")
        
        for label, value in items:
            frame = tk.Frame(parent, bg=COL_BG_WIDGET)
            frame.pack(fill="x", padx=10, pady=2)
            
            if label:
                tk.Label(
                    frame,
                    text=label,
                    font=("Segoe UI", 10, "bold"),
                    bg=COL_BG_WIDGET,
                    fg="#4fc3f7",
                    width=20,
                    anchor="w"
                ).pack(side="left", padx=15, pady=5)
            
            tk.Label(
                frame,
                text=value,
                font=("Segoe UI", 10),
                bg=COL_BG_WIDGET,
                fg=COL_TEXT_LIGHT,
                anchor="w",
                wraplength=400,
                justify="left"
            ).pack(side="left", fill="x", expand=True, padx=(0, 15), pady=5)