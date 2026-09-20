"""
ecg_list_window.py — окно со списком последних ECGLIST_DEFAULT_LIMIT записей ЭКГ.
Сортировка жестко задана: по дате обновления (убывание).
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from theme import COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_CRIT, COL_SELECTION
from models import get_session, ECGRecord, Athlete
from analyzer import MetricAnalyzer
from analysis_dialog import AnalysisDialog
from app_constants import ECGLIST_DEFAULT_LIMIT


class ECGListWindow(tk.Toplevel):
    """Модальное окно со списком последних ECGLIST_DEFAULT_LIMIT записей ЭКГ."""
    
    def __init__(self, parent, db_path=None, athlete_id=None):
        super().__init__(parent)
        self.title(f"📋 Последние {ECGLIST_DEFAULT_LIMIT} записей ЭКГ")
        self.configure(bg=COL_BG_DARK)
        self.geometry("1050x600")
        self.resizable(True, True)
        
        self.db_path = db_path
        self.analyzer = MetricAnalyzer(db_path) if db_path else None
        
        self.transient(parent)
        self.grab_set()
        
        self.update_idletasks()
        x = parent.winfo_x() + 50
        y = parent.winfo_y() + 50
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        self._load_data()
        
        # Закрытие по Escape
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()
    
    def _create_widgets(self):
        # Панель с кнопками управления
        button_frame = tk.Frame(self, bg=COL_BG_WIDGET)
        button_frame.pack(fill="x", padx=10, pady=10)
        
        # Кнопка удаления (используем COL_CRIT из theme.py вместо хардкода)
        tk.Button(
            button_frame,
            text="🗑 Удалить запись",
            command=self._delete_record,
            bg=COL_CRIT,
            fg=COL_SELECTION,
            font=("Segoe UI", 10, "bold"),
            padx=15,
            relief="flat",
            cursor="hand2"
        ).pack(side="left", padx=10)
        
        # Счётчик записей (справа)
        self.count_label = tk.Label(
            button_frame,
            text="Загрузка...",
            font=("Segoe UI", 10),
            bg=COL_BG_WIDGET,
            fg=COL_TEXT_LIGHT
        )
        self.count_label.pack(side="right", padx=10)
        
        # Таблица
        table_frame = tk.Frame(self, bg=COL_BG_DARK)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        columns = ("athlete", "recorded_at", "updated_at", "tp", "stress", "hr")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        # Настройка колонок
        self.tree.heading("athlete", text="ФИО атлета", anchor="w")
        self.tree.heading("recorded_at", text="Дата измерения", anchor="center")
        self.tree.heading("updated_at", text="Дата обновления", anchor="center")
        self.tree.heading("tp", text="TP (мс²)", anchor="e")
        self.tree.heading("stress", text="Стресс (у.е.)", anchor="e")
        self.tree.heading("hr", text="ЧСС (уд/мин)", anchor="e")
        
        # Ширина колонок
        self.tree.column("athlete", width=180, minwidth=150, anchor="w")
        self.tree.column("recorded_at", width=165, minwidth=140, anchor="center")
        self.tree.column("updated_at", width=195, minwidth=170, anchor="center")
        self.tree.column("tp", width=100, minwidth=80, anchor="e")
        self.tree.column("stress", width=100, minwidth=80, anchor="e")
        self.tree.column("hr", width=100, minwidth=80, anchor="e")
        
        # Скроллбар — только вертикальный
        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_y.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")
        
        # Двойной клик для открытия анализа
        self.tree.bind("<Double-1>", self._on_double_click)

    def _delete_record(self):
        """Удаляет выбранную запись ЭКГ БЕЗ подтверждения."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите запись для удаления", parent=self)
            return
        
        item = selection[0]
        record_id = self.tree.item(item, "tags")[0]
        
        session = get_session(self.db_path)
        try:
            record = session.get(ECGRecord, record_id)
            if record:
                # Мгновенное удаление без диалога подтверждения
                session.delete(record)
                session.commit()
                self._load_data()  # Мгновенно перезагружаем список
                # ✅ НОВОЕ: БРОСАЕМ СИГНАЛ через родителя (главное окно)
                # Все, кто подписан на <<ECGDataChanged>>, получат уведомление
                self.master.event_generate("<<ECGDataChanged>>", when="tail")                
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка", f"Не удалось удалить запись:\n{e}", parent=self)
        finally:
            session.close()

    def _load_data(self):
        """Загружает последние 100 записей, отсортированные по дате обновления (убывание)."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        session = get_session(self.db_path)
        try:
            # ЖЕСТКИЙ ЗАПРОС: JOIN + сортировка по updated_at DESC + лимит 100
            q = session.query(ECGRecord, Athlete).join(
                Athlete, ECGRecord.athlete_id == Athlete.id
            ).order_by(
                ECGRecord.updated_at.desc()
            ).limit(ECGLIST_DEFAULT_LIMIT)
            
            records = q.all()
            
            for record, athlete in records:
                athlete_name = f"{athlete.last_name} {athlete.first_name} {athlete.middle_name or ''}".strip()
                
                recorded_at = datetime.datetime.fromisoformat(record.recorded_at).strftime("%d.%m.%Y %H:%M:%S")
                
                if record.updated_at:
                    updated_at = record.updated_at.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3]
                else:
                    updated_at = "—"
                
                tp = f"{record.tp:.0f}" if record.tp else "—"
                stress = f"{record.stress_si:.0f}" if record.stress_si else "—"
                hr = f"{record.mean_hr:.0f}" if record.mean_hr else "—"
                
                self.tree.insert(
                    "",
                    "end",
                    values=(athlete_name, recorded_at, updated_at, tp, stress, hr),
                    tags=(record.id,)
                )
            
            self.count_label.config(text=f"Показано записей: {len(records)}")
            
        finally:
            session.close()
    
    def _on_double_click(self, event):
        """Открывает диалог анализа при двойном клике по записи."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        record_id = self.tree.item(item, "tags")[0]
        
        analysis = self.analyzer.analyze(record_id)
        if analysis:
            AnalysisDialog(self, analysis, self.db_path)