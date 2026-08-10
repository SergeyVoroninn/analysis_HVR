import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from utils import setup_axis_strong

class AccTab:
    def __init__(self, parent_notebook):
        self.frame = tk.Frame(parent_notebook, bg='#1e1e1e')
        parent_notebook.add(self.frame, text="  ACC  ")
        
        container = tk.Frame(self.frame, bg='#1e1e1e')
        container.pack(fill='both', expand=True)
        
        self.fig = Figure(facecolor='#1e1e1e')
        gs = gridspec.GridSpec(2, 1, figure=self.fig, hspace=0.3)
        
        self.ax_raw = self.fig.add_subplot(gs[0, 0])
        self.ax_diff = self.fig.add_subplot(gs[1, 0])
        self.fig.subplots_adjust(left=0.1, right=0.95, top=0.95, bottom=0.12)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        self.info_label = tk.Label(self.frame, text="Данные ACC отобразятся после загрузки файла", 
                                   font=("Segoe UI", 10), bg='#2d2d2d', fg='cyan', anchor='w', padx=20)
        self.info_label.pack(fill='x', padx=10, pady=(5, 0))

    def update(self, df_acc):
        self.ax_raw.clear(); self.ax_diff.clear()
        if df_acc is None or df_acc.empty or 'acc_raw' not in df_acc.columns:
            self.info_label.config(text="Данные ACC отсутствуют в файле", fg='orange')
            for ax in [self.ax_raw, self.ax_diff]: 
                ax.set_facecolor('#2d2d2d'); ax.text(0.5, 0.5, 'Нет данных ACC', ha='center', va='center', fontsize=14, color='gray', transform=ax.transAxes)
                ax.set_xticks([]); ax.set_yticks([])
            self.canvas.draw(); return

        acc_data = df_acc['acc_raw'].dropna()
        roll_mean = acc_data.rolling(50).mean()
        
        setup_axis_strong(self.ax_raw, 11)
        self.ax_raw.plot(acc_data.index, acc_data.values, linewidth=0.6, label='Raw ACC', alpha=0.6)
        self.ax_raw.plot(acc_data.index, roll_mean, linewidth=1.5, color='orange', label='Rolling mean (50)')
        self.ax_raw.set_title('Акселерометрия (ACC) и скользящее среднее')
        self.ax_raw.set_xlabel('Индекс записи'); self.ax_raw.set_ylabel('ACC')
        self.ax_raw.legend(loc='upper right')
        
        setup_axis_strong(self.ax_diff, 11)
        diff_1 = acc_data.diff().abs()
        self.ax_diff.plot(diff_1.index, diff_1.values, linewidth=0.7, color='purple')
        self.ax_diff.set_title('Абсолютные разности ACC (скорость изменения)')
        self.ax_diff.set_xlabel('Индекс'); self.ax_diff.set_ylabel('|ΔACC|')
        
        self.info_label.config(text=f'Загружено отсчётов ACC: {len(acc_data):,}', fg='#00ff00')
        self.canvas.draw()