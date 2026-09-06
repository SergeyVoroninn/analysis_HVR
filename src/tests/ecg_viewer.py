"""
ecg_viewer.py — интерактивный просмотрщик ЭКГ с RR-интервалами.
Показывает сырой/отфильтрованный ЭКГ, R-пики и тахограмму.
"""
import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import tkinter as tk
from tkinter import filedialog, messagebox

# Добавляем корневую папку проекта в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import analysis as hrv

# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================
FS_ECG = 130.0   # Частота дискретизации ЭКГ (Polar H10)
# ==============================================================================


class ECGViewer:
    """Интерактивный просмотрщик ЭКГ с RR-интервалами."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("ECG + RR Viewer — Просмотрщик ЭКГ и RR-интервалов")
        self.root.geometry("1400x1000")
        self.root.configure(bg='#2b2b2b')
        
        # Текущий файл и данные
        self.current_file = None
        self.ecg_raw = None
        self.ecg_clean = None
        self.peaks_samples = None
        self.rr_intervals = None
        self.rr_times = None  # Время каждого RR-интервала
        
        # Загружаем список файлов из etalons.json
        self.etalons = self.load_etalons()
        
        # Создаем интерфейс
        self.create_ui()
        
        # Если есть файлы в списке, выбираем первый
        if self.etalons:
            self.load_file_from_etalon(self.etalons[0])

        root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def load_etalons(self):
        """Загружает список файлов из etalons.json."""
        etalons_path = os.path.join(os.path.dirname(__file__), "etalons.json")
        try:
            with open(etalons_path, "r", encoding="utf-8") as f:
                content = f.read().encode('utf-8')
                if content.startswith(b'\xef\xbb\xbf'):
                    content = content[3:]
                return json.loads(content.decode('utf-8'))
        except Exception as e:
            print(f"Ошибка чтения etalons.json: {e}")
            return []
    
    def create_ui(self):
        """Создает пользовательский интерфейс."""
        # Верхняя панель с кнопками
        top_frame = tk.Frame(self.root, bg='#2b2b2b', height=60)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Кнопка выбора файла из списка
        btn_list = tk.Button(
            top_frame,
            text="📋 Выбрать из списка",
            command=self.show_file_list,
            bg='#0078d4',
            fg='white',
            font=('Arial', 10, 'bold'),
            width=20,
            height=2
        )
        btn_list.pack(side=tk.LEFT, padx=5)
        
        # Кнопка выбора файла через диалог
        btn_browse = tk.Button(
            top_frame,
            text="📁 Открыть файл...",
            command=self.browse_file,
            bg='#4a4a4a',
            fg='white',
            font=('Arial', 10),
            width=20,
            height=2
        )
        btn_browse.pack(side=tk.LEFT, padx=5)
        
        # Информация о текущем файле
        self.file_info_label = tk.Label(
            top_frame,
            text="Файл не выбран",
            bg='#2b2b2b',
            fg='white',
            font=('Arial', 10),
            anchor='w'
        )
        self.file_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Основная область с графиками
        main_frame = tk.Frame(self.root, bg='#2b2b2b')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Создаем matplotlib figure с 4 подграфиками
        self.fig, self.axes = plt.subplots(4, 1, figsize=(14, 12), sharex=False)
        self.fig.patch.set_facecolor('#1e1e1e')
        for ax in self.axes:
            ax.set_facecolor('#1e1e1e')
        
        # Встраиваем график в tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=main_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Добавляем toolbar для навигации
        toolbar = NavigationToolbar2Tk(self.canvas, main_frame)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Нижняя панель со статистикой
        stats_frame = tk.Frame(self.root, bg='#2b2b2b', height=100)
        stats_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.stats_label = tk.Label(
            stats_frame,
            text="Статистика будет отображена здесь",
            bg='#1e1e1e',
            fg='white',
            font=('Consolas', 10),
            justify=tk.LEFT,
            anchor='w',
            padx=10,
            pady=5
        )
        self.stats_label.pack(fill=tk.BOTH, expand=True)
    
    def show_file_list(self):
        """Показывает окно со списком файлов из etalons.json."""
        if not self.etalons:
            messagebox.showinfo("Информация", "Список файлов пуст. Используйте 'Открыть файл...'")
            return
        
        list_window = tk.Toplevel(self.root)
        list_window.title("Выберите файл ЭКГ")
        list_window.geometry("600x500")
        list_window.configure(bg='#2b2b2b')
        
        title_label = tk.Label(
            list_window,
            text="Доступные файлы ЭКГ:",
            font=('Arial', 12, 'bold'),
            bg='#2b2b2b',
            fg='white'
        )
        title_label.pack(pady=10)
        
        listbox = tk.Listbox(
            list_window,
            bg='#1e1e1e',
            fg='white',
            selectbackground='#0078d4',
            font=('Consolas', 9),
            height=20
        )
        scrollbar = tk.Scrollbar(list_window, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        
        for etalon in self.etalons:
            filename = os.path.basename(etalon["file"])
            source = etalon.get("source", "Unknown")
            listbox.insert(tk.END, f"{filename}\n  ({source})")
        
        def on_select():
            selection = listbox.curselection()
            if selection:
                idx = selection[0]
                list_window.destroy()
                self.load_file_from_etalon(self.etalons[idx])
        
        btn_select = tk.Button(
            list_window,
            text="✓ Выбрать",
            command=on_select,
            bg='#0078d4',
            fg='white',
            font=('Arial', 10, 'bold'),
            width=15,
            height=2
        )
        btn_select.pack(pady=10)
    
    def browse_file(self):
        """Открывает диалог выбора файла."""
        file_path = filedialog.askopenfilename(
            title="Выберите файл ЭКГ",
            initialdir=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "reference")),
            filetypes=[
                ("Файлы ЭКГ", "*.teamloggerh10 *.ecg *.txt"),
                ("Все файлы", "*.*")
            ]
        )
        
        if file_path:
            self.load_file(file_path)
    
    def load_file_from_etalon(self, etalon):
        """Загружает файл из списка etalons."""
        file_path = etalon["file"]
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", file_path))
        
        if os.path.exists(file_path):
            self.load_file(file_path)
        else:
            messagebox.showerror("Ошибка", f"Файл не найден:\n{file_path}")
    
    def load_file(self, file_path):
        """Загружает RR напрямую из секции [RR] файла."""
        if not os.path.exists(file_path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{file_path}")
            return
    
        print(f"📂 Загрузка: {os.path.basename(file_path)}")
        self.current_file = file_path
        self.file_info_label.config(text=f"Файл: {os.path.basename(file_path)}")
    
        # Загружаем данные
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = f.read()
    
        # === КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ===
        # Используем готовые RR из файла, а не детектируем их заново из ЭКГ
        self.rr_intervals = hrv.parse_rr(raw_data)
    
        if not self.rr_intervals:
            messagebox.showerror("Ошибка", "В файле не найдена секция [RR]")
            return
    
        # ЭКГ оставляем только для визуального сравнения
        self.ecg_raw = hrv.parse_ecg(raw_data, clean=False)
        self.ecg_clean = hrv.parse_ecg(raw_data, clean=True, fs=FS_ECG)
    
        # === ИСПРАВЛЕНИЕ РАЗМЕРНОСТИ МАССИВОВ ===
        rr_array = np.array(self.rr_intervals)
        
        # self.rr_times теперь имеет ту же длину (N), что и rr_array.
        # Это время (в секундах) момента окончания каждого RR-интервала.
        self.rr_times = np.cumsum(rr_array) / 1000.0  
    
        # Вычисляем индексы семплов для отрисовки вертикальных линий на ЭКГ
        self.peaks_samples = (self.rr_times * FS_ECG).astype(int)
    
        # Отображаем графики
        self.plot_data()
    
        # Обновляем статистику
        self.update_statistics()    
        
    def plot_data(self):
        """Отображает данные на графиках."""
        # Очищаем графики
        for ax in self.axes:
            ax.clear()
        
        duration_ecg = len(self.ecg_raw) / FS_ECG
        time_ecg = np.arange(len(self.ecg_raw)) / FS_ECG
        
        # График 1: Сырой ЭКГ
        self.axes[0].plot(time_ecg, self.ecg_raw, color='lightgray', linewidth=0.5, alpha=0.7, label='Raw')
        self.axes[0].set_ylabel("ЭКГ (сырой)", color='white', fontsize=10)
        self.axes[0].legend(loc='upper right')
        self.axes[0].grid(True, alpha=0.3)
        self.axes[0].set_title("Сырой сигнал ЭКГ", color='white', fontsize=11, fontweight='bold')
        self.axes[0].tick_params(colors='white')
        
        # График 2: Очищенный ЭКГ с R-пиками и вертикальными линиями
        self.axes[1].plot(time_ecg, self.ecg_clean, color='#1f77b4', linewidth=0.5, alpha=0.8, label='Cleaned')
        if len(self.peaks_samples) > 0:
            peak_times = self.peaks_samples / FS_ECG
            # Вертикальные линии в местах R-пиков
            for pt in peak_times:
                self.axes[1].axvline(x=pt, color='red', alpha=0.3, linewidth=0.5)
            # Точки R-пиков
            self.axes[1].scatter(peak_times, self.ecg_clean[self.peaks_samples], 
                               color='red', s=15, zorder=5, label=f'R-peaks ({len(self.peaks_samples)})')
        self.axes[1].set_ylabel("ЭКГ (очищенный)", color='white', fontsize=10)
        self.axes[1].legend(loc='upper right')
        self.axes[1].grid(True, alpha=0.3)
        self.axes[1].set_title("Отфильтрованный сигнал ЭКГ с R-пиками", 
                              color='white', fontsize=11, fontweight='bold')
        self.axes[1].tick_params(colors='white')
        
        # График 3: Тахограмма (RR-интервалы во времени)
        if len(self.rr_intervals) > 0:
            rr_array = np.array(self.rr_intervals)
            self.axes[2].plot(self.rr_times, rr_array, 'g-', linewidth=1.5, marker='o', markersize=4, label='RR intervals')
            self.axes[2].axhline(y=np.mean(rr_array), color='yellow', linestyle='--', linewidth=1, label=f'Mean: {np.mean(rr_array):.0f} мс')
            self.axes[2].set_ylabel("RR (мс)", color='white', fontsize=10)
            self.axes[2].legend(loc='upper right')
            self.axes[2].grid(True, alpha=0.3)
            self.axes[2].set_title("Тахограмма: RR-интервалы во времени", color='white', fontsize=11, fontweight='bold')
            self.axes[2].tick_params(colors='white')
        else:
            self.axes[2].text(0.5, 0.5, "RR-интервалы не найдены", 
                             ha='center', va='center', color='white', fontsize=12)
        
        # График 4: Разности RR (для оценки вариабельности)
        if len(self.rr_intervals) > 1:
            rr_diff = np.diff(self.rr_intervals)
            diff_times = self.rr_times[1:]  # Время второго пика в каждой паре
            self.axes[3].plot(diff_times, rr_diff, 'orange', linewidth=1.5, marker='s', markersize=3, label='RR diff')
            self.axes[3].axhline(y=0, color='red', linestyle='-', linewidth=1, alpha=0.5)
            self.axes[3].set_ylabel("ΔRR (мс)", color='white', fontsize=10)
            self.axes[3].set_xlabel("Время (секунды)", color='white', fontsize=10)
            self.axes[3].legend(loc='upper right')
            self.axes[3].grid(True, alpha=0.3)
            self.axes[3].set_title("Разности соседних RR-интервалов (вариабельность)", color='white', fontsize=11, fontweight='bold')
            self.axes[3].tick_params(colors='white')
        else:
            self.axes[3].text(0.5, 0.5, "Недостаточно данных для разностей", 
                             ha='center', va='center', color='white', fontsize=12)
        
        # Обновляем canvas
        self.fig.tight_layout()
        self.canvas.draw()

        # Принудительное освобождение памяти
        import gc
        gc.collect()
    
    def update_statistics(self):
        """Обновляет панель статистики."""
        duration_sec = len(self.ecg_raw) / FS_ECG
        
        stats_text = f"📊 Статистика записи\n"
        stats_text += f"{'='*70}\n"
        stats_text += f"Длительность: {duration_sec:.1f} сек ({duration_sec/60:.1f} мин)\n"
        stats_text += f"Семплов ЭКГ: {len(self.ecg_raw)} (fs={FS_ECG} Гц)\n"
        
        stats_text += f"\nRR-интервалы:\n"
        
        if self.rr_intervals:
            rr_array = np.array(self.rr_intervals)
            mean_rr = np.mean(rr_array)
            mean_hr = 60000.0 / mean_rr
            std_rr = np.std(rr_array)
            rmssd = np.sqrt(np.mean(np.diff(rr_array)**2))
            
            stats_text += f"  Количество: {len(self.rr_intervals)}\n"
            stats_text += f"  Средний RR: {mean_rr:.1f} мс\n"
            stats_text += f"  Средний HR: {mean_hr:.1f} уд/мин\n"
            stats_text += f"  SDNN: {std_rr:.1f} мс\n"
            stats_text += f"  RMSSD: {rmssd:.1f} мс\n"
            stats_text += f"  Мин RR: {np.min(rr_array):.1f} мс\n"
            stats_text += f"  Макс RR: {np.max(rr_array):.1f} мс\n"
            
            # Оценка качества детекции
            rr_diff = np.diff(rr_array)
            large_diffs = np.sum(np.abs(rr_diff) > 100)  # Разности > 100 мс
            if large_diffs > len(rr_diff) * 0.1:
                stats_text += f"\n⚠️  Много больших скачков RR (>100 мс): {large_diffs}\n"
                stats_text += f"   Возможны ложные срабатывания или пропуски пиков\n"
            else:
                stats_text += f"\n✅ Качество детекции хорошее\n"
        else:
            stats_text += f"  ❌ RR-интервалы не найдены!\n"
        
        stats_text += f"{'='*70}"
        
        self.stats_label.config(text=stats_text)

    def on_closing(self):
        """Корректное закрытие приложения."""
        try:
            # Отключаем все callback'и matplotlib
            if hasattr(self, 'canvas'):
                self.canvas.mpl_disconnect('button_press_event')
                self.canvas.mpl_disconnect('scroll_event')
            
            # Закрываем figure
            if hasattr(self, 'fig'):
                plt.close(self.fig)
            
            # Уничтожаем окно
            self.root.destroy()
        except Exception as e:
            print(f"Ошибка при закрытии: {e}")
            import sys
            sys.exit(0)


def main():
    """Главная функция запуска приложения."""
    root = tk.Tk()
    app = ECGViewer(root)
    
    # Обработчик закрытия окна
    def on_closing():
        """Корректное закрытие приложения."""
        try:
            # Закрываем все matplotlib figure
            plt.close('all')
        except:
            pass
        try:
            # Уничтожаем tkinter окно
            root.destroy()
        except:
            pass
    
    # Привязываем обработчик к закрытию окна
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    root.mainloop()


if __name__ == "__main__":
    try:
        import matplotlib
        matplotlib.use('TkAgg')  # Явно указываем бэкенд
    except ImportError as e:
        print(f"❌ Ошибка: Не установлена необходимая библиотека: {e}")
        print("Установите их командой: pip install matplotlib")
        sys.exit(1)
    
    main()