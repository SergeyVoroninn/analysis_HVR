import sys

# ==========================================
# 1. УМНАЯ ПРОВЕРКА ЗАВИСИМОСТЕЙ
# ==========================================
REQUIRED_PACKAGES = ['sqlalchemy', 'bcrypt', 'pandas', 'matplotlib']
missing_packages = []

for package in REQUIRED_PACKAGES:
    try:
        __import__(package)
    except ImportError:
        missing_packages.append(package)

if missing_packages:
    # Пытаемся использовать tkinter для красивого сообщения
    try:
        import tkinter as tk
        from tkinter import messagebox
        
        root_check = tk.Tk()
        root_check.withdraw() # Скрываем главное окно
        
        install_cmd = f"pip install {' '.join(missing_packages)}"
        messagebox.showerror(
            "Отсутствуют зависимости",
            f"Для работы программы не хватает следующих библиотек:\n\n"
            f"❌ {', '.join(missing_packages)}\n\n"
            f"Пожалуйста, откройте командную строку и выполните:\n"
            f"👉 {install_cmd}\n\n"
            f"(Библиотека tkinter встроена в Python и не требует установки)"
        )
    except ImportError:
        # Если даже tkinter сломан, выводим в консоль
        print("="*60)
        print("КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют необходимые библиотеки.")
        print(f"Установите их командой: pip install {' '.join(missing_packages)}")
        print("Если ошибка указывает на отсутствие 'tkinter', переустановите Python,")
        print("обязательно отметив галочку 'tcl/tk and IDLE' при установке.")
        print("="*60)
    sys.exit(1) # Завершаем программу, если чего-то не хватает

# ==========================================
# 2. ОСНОВНЫЕ ИМПОРТЫ (теперь они безопасны)
# ==========================================
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd

from tab_hrv import HrvTab
from tab_quality import QualityTab
from tab_ecg import EcgTab
from tab_rr import RrTab
from tab_acc import AccTab
from data_processor import load_and_process_teamlogger
import db_manager # Наш модуль для работы с БД

class TimelineViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ИИшенка на спорте")
        self.root.state('zoomed')
        self.root.configure(bg='#1e1e1e')
        
        # Данные
        self.result = None
        self.df_rr = None
        self.df_acc = None
        self.current_header = None
        
        # Текущий пользователь БД
        # БЫЛО:
        # self.current_user = db_manager.get_or_create_default_user()
        
        # СТАЛО:
        user_data = db_manager.get_or_create_default_user()
        self.current_user_id = user_data["id"]
        self.current_username = user_data["username"]
        
        self.create_widgets()
        
        # Глобальные горячие клавиши
        self.root.bind('<Escape>', lambda e: self.root.destroy())
        self.root.bind('<F11>', lambda e: self.toggle_fullscreen())
        self.root.bind('<Up>', lambda e: self.tab_ecg.navigate(-1))
        self.root.bind('<Down>', lambda e: self.tab_ecg.navigate(1))
        self.root.bind('<Page_Up>', lambda e: self.tab_ecg.navigate(-5))
        self.root.bind('<Page_Down>', lambda e: self.tab_ecg.navigate(5))
        self.root.bind('<Home>', lambda e: self.tab_ecg.navigate(-self.tab_ecg.current_page))
        self.root.bind('<End>', lambda e: self.tab_ecg.navigate(self.tab_ecg.total_pages))
        
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)

    def on_tab_changed(self, event):
        idx = self.notebook.index(self.notebook.select())
        if idx == 0 and self.result is not None: self.tab_quality.canvas.draw()
        elif idx == 1 and self.result is not None: self.tab_ecg.canvas.draw()
        elif idx == 2 and self.df_rr is not None: self.tab_rr.canvas.draw()
        elif idx == 3 and self.df_acc is not None: self.tab_acc.canvas.draw()
        elif idx == 4 and self.df_rr is not None: self.tab_hrv.canvas.draw()

    def create_widgets(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook.Tab', background='#e8f5e9', foreground='black', padding=[15, 8], font=('Segoe UI', 11, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', "#F8F6F6")], foreground=[('selected', '#2e7d32')])

        control_frame = tk.Frame(self.root, bg='#2d2d2d', height=60)
        control_frame.pack(fill='x', padx=10, pady=10)
        control_frame.pack_propagate(False)
        
        tk.Label(control_frame, text="ИИшенка на спорте", font=("Segoe UI", 20, "bold"), bg='#2d2d2d', fg='white').pack(side='left', padx=20, pady=10)
        
        
        # --- Блок пользователя и датчика ---
        user_frame = tk.Frame(control_frame, bg='#2d2d2d')
        user_frame.pack(side='left', padx=20)
        tk.Label(user_frame, text=f"👤 {self.current_username}", font=("Segoe UI", 11), bg='#2d2d2d', fg='#00ff00').pack(side='left', padx=5)
        
        sensor_frame = tk.Frame(control_frame, bg='#2d2d2d')
        sensor_frame.pack(side='left', padx=20)
        tk.Label(sensor_frame, text="Датчик:", font=("Segoe UI", 11), bg='#2d2d2d', fg='white').pack(side='left', padx=5)
        
        self.sensor_var = tk.StringVar(value="Polar H10")
        ttk.Combobox(sensor_frame, textvariable=self.sensor_var, values=["Polar H10", "Другой датчик"], state="readonly", font=("Segoe UI", 10), width=25).pack(side='left', padx=5)
        
        # --- Кнопки управления ---
        btn_frame = tk.Frame(control_frame, bg='#2d2d2d')
        btn_frame.pack(side='right', padx=20)

        tk.Button(btn_frame, text="📜 История БД", command=self.show_db_history, font=("Segoe UI", 11, "bold"), bg='#FF9800', fg='white', relief='flat', padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        
        self.btn_save_db = tk.Button(btn_frame, text="💾 Сохранить в БД", command=self.save_to_database, 
                                     font=("Segoe UI", 11, "bold"), bg='#2196F3', fg='white', relief='flat', 
                                     padx=15, pady=8, cursor='hand2', state='disabled')
        self.btn_save_db.pack(side='left', padx=5)
        
        tk.Button(btn_frame, text="📂 Выбрать файл", command=self.load_file, font=("Segoe UI", 11, "bold"), bg='#4CAF50', fg='white', relief='flat', padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="✕ Выход", command=self.root.destroy, font=("Segoe UI", 11), bg='#f44336', fg='white', relief='flat', padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        
        self.status_label = tk.Label(self.root, text="Готов к работе. Выберите файл .teamloggerh10", font=("Segoe UI", 10), bg='#2d2d2d', fg='#00ff00', anchor='w', padx=20, pady=5)
        self.status_label.pack(fill='x', padx=10, pady=(0, 5))
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # Инициализация вкладок
        self.tab_quality = QualityTab(self.notebook)
        self.tab_ecg = EcgTab(self.notebook)
        self.tab_rr = RrTab(self.notebook)
        self.tab_acc = AccTab(self.notebook)
        self.tab_hrv = HrvTab(self.notebook)
        
        # Заглушка ECG
        self.tab_ecg.ax_overview.set_facecolor('#fcf7f7')
        self.tab_ecg.ax_overview.text(0.5, 0.5, 'Загрузите файл для отображения', ha='center', va='center', fontsize=14, color='gray', transform=self.tab_ecg.ax_overview.transAxes)
        self.tab_ecg.ax_overview.set_xticks([]); self.tab_ecg.ax_overview.set_yticks([])
        self.tab_ecg.canvas.draw()

    def load_file(self):
        file_path = filedialog.askopenfilename(title="Выберите файл .teamloggerh10", filetypes=[("TeamLogger H10 files", "*.teamloggerh10"), ("All files", "*.*")])
        if not file_path: return
            
        if self.sensor_var.get() != "Polar H10":
            messagebox.showinfo("Информация", "Выбран другой датчик. Полная поддержка реализована только для Polar H10.")
        
        try:
            self.status_label.config(text="Чтение и обработка файла...", fg='orange')
            self.root.update()
            
            self.result, self.df_rr, self.df_acc, self.current_header = load_and_process_teamlogger(file_path)

            print(f"\n=== ОТЛАДКА ЗАГРУЗКИ ИЗ ФАЙЛА ===")
            print(f"self.result type: {type(self.result)}")
            if isinstance(self.result, list):
                print(f"self.result len: {len(self.result)}")
                if len(self.result) > 0:
                    print(f"self.result[0] type: {type(self.result[0])}")
                    if isinstance(self.result[0], dict):
                        print(f"self.result[0] keys: {self.result[0].keys()}")
                        print(f"self.result[0]['values'] len: {len(self.result[0].get('values', []))}")
                    elif isinstance(self.result[0], (int, float)):
                        print(f"Это плоский список чисел")
            elif hasattr(self.result, 'shape'):
                print(f"self.result shape: {self.result.shape}")
            print(f"self.df_rr type: {type(self.df_rr)}, shape: {self.df_rr.shape}")
            print(f"self.df_acc type: {type(self.df_acc)}, shape: {self.df_acc.shape}")
            print("=====================================\n")
            
            self.status_label.config(text="Построение графиков...", fg='orange')
            self.root.update()
            
            self.tab_quality.update(self.result)
            self.tab_ecg.update(self.result)
            self.tab_rr.update(self.df_rr)
            self.tab_acc.update(self.df_acc)
            self.tab_hrv.update(self.df_rr)
            
            rr_count = len(self.df_rr) if self.df_rr is not None and not (isinstance(self.df_rr, pd.DataFrame) and self.df_rr.empty) else 0
            acc_count = len(self.df_acc) if self.df_acc is not None and not (isinstance(self.df_acc, pd.DataFrame) and self.df_acc.empty) else 0
            
            self.status_label.config(text=f"✅ Файл загружен. ECG: {len(self.result):,} точек | RR: {rr_count} | ACC: {acc_count}", fg='#00ff00')
            
            self.btn_save_db.config(state='normal')
            
        except ValueError as ve:
            messagebox.showerror("Ошибка данных", str(ve))
            self.status_label.config(text="Ошибка в данных файла", fg='red')
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка при обработке файла:\n{str(e)}")
            self.status_label.config(text="Ошибка", fg='red')

    def save_to_database(self):
        if self.result is None or self.current_header is None:
            messagebox.showwarning("Внимание", "Сначала загрузите файл!")
            return
            
        polar_id = self.current_header.get("polar_id", "Unknown")
        record_datetime = self.current_header.get("datetime", "")
        
        # Определяем длину данных ЭКГ (работает и для DataFrame, и для списка)
        ecg_length = len(self.result)
        
        # 🟢 ПРОВЕРКА НА ДУБЛИКАТ
        if db_manager.is_duplicate_recording(self.current_user_id, polar_id, record_datetime, ecg_length):
            messagebox.showwarning(
                "Дубликат", 
                f"Запись с датчика {polar_id} за {record_datetime} уже сохранена в базе данных!\n\n"
                "Повторное сохранение отменено, чтобы избежать дублирования."
            )
            self.status_label.config(text="⚠️ Сохранение отменено: файл уже в базе", fg='orange')
            self.btn_save_db.config(state='disabled') # Блокируем кнопку
            return

        # Если дубликата нет, спрашиваем подтверждение
        if not messagebox.askyesno("Подтверждение", f"Сохранить новую сессию от {record_datetime} в базу данных?"):
            return

        try:
            self.status_label.config(text="💾 Сохранение в базу данных...", fg='orange')
            self.root.update()
            
            record_id = db_manager.save_session_to_db(
                user_id=self.current_user_id,
                header=self.current_header,
                ecg_result=self.result,
                df_rr=self.df_rr,
                df_acc=self.df_acc
            )
            
            self.status_label.config(text=f"✅ Успешно сохранено в БД (ID записи: {record_id})", fg='#00ff00')
            messagebox.showinfo("Успех", "Данные успешно сохранены в локальную базу данных!")
            
            # Деактивируем кнопку после успешного сохранения
            self.btn_save_db.config(state='disabled')
            
        except Exception as e:
            self.status_label.config(text="❌ Ошибка сохранения в БД", fg='red')
            messagebox.showerror("Ошибка БД", f"Не удалось сохранить данные:\n{str(e)}")
            
    def toggle_fullscreen(self):
        current_state = self.root.attributes('-fullscreen')
        self.root.attributes('-fullscreen', not current_state)

    def show_db_history(self):
        """Открывает окно со списком сохраненных записей"""
        history_win = tk.Toplevel(self.root)
        history_win.title("История записей в БД")
        history_win.geometry("750x450")
        history_win.configure(bg='#2d2d2d')
        history_win.transient(self.root)
        
        tk.Label(history_win, text="Дважды кликните — загрузить | Выделите и нажмите 'Удалить' — стереть", 
                 font=("Segoe UI", 10), bg='#2d2d2d', fg='white').pack(pady=10)
        
        # Настраиваем таблицу
        columns = ("id", "datetime", "polar_id", "ecg_points")
        tree = ttk.Treeview(history_win, columns=columns, show="headings", style="Custom.Treeview")
        
        tree.heading("id", text="ID")
        tree.heading("datetime", text="Дата и время записи")
        tree.heading("polar_id", text="Датчик")
        tree.heading("ecg_points", text="Точек ЭКГ")
        
        tree.column("id", width=50, anchor="center")
        tree.column("datetime", width=200, anchor="center")
        tree.column("polar_id", width=150, anchor="center")
        tree.column("ecg_points", width=120, anchor="center")
        
        tree.pack(fill="both", expand=True, padx=15, pady=5)
        
        # Загружаем данные из БД
        records = db_manager.get_user_recordings_list(self.current_user_id)
        
        if not records:
            tk.Label(history_win, text="В базе данных пока нет сохраненных записей.", 
                     font=("Segoe UI", 11), bg='#2d2d2d', fg='#ff9800').pack(pady=20)
        else:
            for rec in records:
                tree.insert("", "end", values=(
                    rec["id"], 
                    rec["datetime"], 
                    rec["polar_id"], 
                    f"{rec['ecg_points']:,}"
                ), iid=rec["id"])
                
        # Двойной клик — загрузка
        tree.bind("<Double-1>", lambda e: self._load_from_db_selected(tree, history_win))
        
        #  БЛОК КНОПОК УПРАВЛЕНИЯ
        btn_frame = tk.Frame(history_win, bg='#2d2d2d')
        btn_frame.pack(pady=10)
        
        def delete_selected():
            """Удаляет выбранную запись из БД"""
            selected_items = tree.selection()
            if not selected_items:
                messagebox.showwarning("Внимание", "Сначала выберите запись для удаления!")
                return
                
            record_id = int(selected_items[0])
            # Находим данные записи для красивого сообщения
            item_values = tree.item(selected_items[0])["values"]
            rec_datetime = item_values[1]
            rec_polar = item_values[2]
            
            # Подтверждение удаления
            confirm = messagebox.askyesno(
                "Подтверждение удаления",
                f"Вы уверены, что хотите БЕЗВОЗВРАТНО удалить запись?\n\n"
                f"📅 Дата: {rec_datetime}\n"
                f" Датчик: {rec_polar}\n"
                f"🆔 ID в БД: {record_id}\n\n"
                f"Это действие нельзя отменить!"
            )
            
            if not confirm:
                return
                
            try:
                if db_manager.delete_recording_by_id(record_id):
                    # Удаляем строку из таблицы
                    tree.delete(selected_items[0])
                    messagebox.showinfo("Успех", f"Запись ID {record_id} успешно удалена из базы данных.")
                    
                    # Если удалили ту запись, которая сейчас загружена — очищаем интерфейс
                    if self.current_header and self.current_header.get("datetime") == rec_datetime:
                        self.status_label.config(text="⚠️ Текущая запись была удалена из БД", fg='orange')
                else:
                    messagebox.showerror("Ошибка", "Не удалось найти запись в базе данных.")
            except Exception as e:
                messagebox.showerror("Ошибка БД", f"Не удалось удалить запись:\n{str(e)}")
        
        # Кнопка удаления (оранжевая, с иконкой)
        tk.Button(btn_frame, text="🗑 Удалить выбранную", command=delete_selected, 
                  font=("Segoe UI", 10, "bold"), bg='#FF5722', fg='white', relief='flat', 
                  padx=20, pady=6, cursor='hand2').pack(side='left', padx=5)
        
        tk.Button(btn_frame, text="Закрыть", command=history_win.destroy, 
                  font=("Segoe UI", 10, "bold"), bg='#757575', fg='white', relief='flat', 
                  padx=20, pady=6, cursor='hand2').pack(side='left', padx=5)

    def _load_from_db_selected(self, tree, history_win):
        """Загружает выбранную из таблицы запись в приложение"""
        selected_items = tree.selection()
        if not selected_items:
            return
            
        record_id = int(selected_items[0])
        history_win.destroy() # Закрываем окно истории
        
        self.status_label.config(text=f"⏳ Загрузка записи ID {record_id} из базы данных...", fg='orange')
        self.root.update()
        
        try:
            print(f"\n=== ОТЛАДКА ЗАГРУЗКИ ИЗ БД (ID: {record_id}) ===")
            
            # Получаем полные данные из БД
            data = db_manager.get_full_recording_by_id(record_id)
            if not data:
                messagebox.showerror("Ошибка", "Запись не найдена в базе данных.")
                return
                
            self.current_header, self.result, self.df_rr, self.df_acc = data
            
            print(f"self.result type: {type(self.result)}, len: {len(self.result) if hasattr(self.result, '__len__') else 'N/A'}")
            print(f"self.df_rr type: {type(self.df_rr)}")
            print(f"self.df_acc type: {type(self.df_acc)}")
            
            if hasattr(self.df_rr, 'shape'):
                print(f"self.df_rr shape: {self.df_rr.shape}")
                print(f"self.df_rr columns: {self.df_rr.columns.tolist() if hasattr(self.df_rr, 'columns') else 'N/A'}")
            else:
                print(f"self.df_rr is NOT a DataFrame! It's: {type(self.df_rr)}")
                
            if hasattr(self.df_acc, 'shape'):
                print(f"self.df_acc shape: {self.df_acc.shape}")
            else:
                print(f"self.df_acc is NOT a DataFrame! It's: {type(self.df_acc)}")
            
            print("=== НАЧАЛО ОБНОВЛЕНИЯ ВКЛАДОК ===")
            
            # 🟢 ДОБАВЬТЕ ЭТИ СТРОКИ ДЛЯ ОТЛАДКИ:
            print(f"df_rr empty: {self.df_rr.empty if hasattr(self.df_rr, 'empty') else 'N/A'}")
            print(f"df_rr len: {len(self.df_rr) if self.df_rr is not None else 0}")
            print(f"df_acc empty: {self.df_acc.empty if hasattr(self.df_acc, 'empty') else 'N/A'}")
            print(f"df_acc len: {len(self.df_acc) if self.df_acc is not None else 0}")
            
            print("1. Обновляем tab_quality...")
            self.tab_quality.update(self.result)
            
            print("2. Обновляем tab_ecg...")
            self.tab_ecg.update(self.result)
            
            print("3. Обновляем tab_rr...")
            self.tab_rr.update(self.df_rr)
            
            print("4. Обновляем tab_acc...")
            self.tab_acc.update(self.df_acc)
            
            print("5. Обновляем tab_hrv...")
            self.tab_hrv.update(self.df_rr)
            
            print("=== ВСЕ ВКЛАДКИ ОБНОВЛЕНЫ ===\n")
            
            rr_count = len(self.df_rr) if self.df_rr is not None and not (isinstance(self.df_rr, pd.DataFrame) and self.df_rr.empty) else 0
            acc_count = len(self.df_acc) if self.df_acc is not None and not (isinstance(self.df_acc, pd.DataFrame) and self.df_acc.empty) else 0
            
            self.status_label.config(
                text=f"✅ Загружено из БД (ID: {record_id}). ECG: {len(self.result):,} точек | RR: {rr_count} | ACC: {acc_count}", 
                fg='#00ff00'
            )
            
            # Кнопка сохранения неактивна, так как данные уже в БД
            self.btn_save_db.config(state='disabled')
            
        except Exception as e:
            import traceback
            print(f"\n❌ ОШИБКА ПРИ ЗАГРУЗКЕ ИЗ БД:")
            print(traceback.format_exc())
            messagebox.showerror("Ошибка", f"Не удалось загрузить данные из БД:\n{str(e)}")
            self.status_label.config(text="❌ Ошибка загрузки из БД", fg='red')       


if __name__ == "__main__":
    root = tk.Tk()
    app = TimelineViewerApp(root)
    root.mainloop()