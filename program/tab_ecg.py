import tkinter as tk
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from utils import setup_axis_strong

class EcgTab:
    def __init__(self, parent_notebook):
        self.frame = tk.Frame(parent_notebook, bg='#1e1e1e')
        parent_notebook.add(self.frame, text="  ECG  ")
        
        container = tk.Frame(self.frame, bg='#1e1e1e')
        container.pack(fill='both', expand=True)
        
        self.fig = Figure(facecolor='#1e1e1e')
        gs = gridspec.GridSpec(7, 1, figure=self.fig)
        
        self.ax_overview = self.fig.add_subplot(gs[0, 0])
        self.ax_detail1 = self.fig.add_subplot(gs[1:4, 0])
        self.ax_detail2 = self.fig.add_subplot(gs[4:7, 0])
        self.fig.subplots_adjust(left=0.08, right=0.95, top=0.95, bottom=0.08, hspace=0.05)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        # === ПАНЕЛЬ НАВИГАЦИИ ===
        nav_frame = tk.Frame(self.frame, bg='#2d2d2d', height=50)
        nav_frame.pack(fill='x', padx=10, pady=5)
        
        tk.Button(nav_frame, text="⏮ В начало", command=lambda: self.navigate(-self.current_page), 
                 font=("Segoe UI", 10, "bold"), bg='#4CAF50', fg='white', relief='flat', 
                 padx=15, pady=5, cursor='hand2').pack(side='left', padx=5)
        tk.Button(nav_frame, text="◀ Назад", command=lambda: self.navigate(-1), 
                 font=("Segoe UI", 10, "bold"), bg='#2196F3', fg='white', relief='flat', 
                 padx=15, pady=5, cursor='hand2').pack(side='left', padx=5)
        tk.Button(nav_frame, text="Вперед ▶", command=lambda: self.navigate(1), 
                 font=("Segoe UI", 10, "bold"), bg='#2196F3', fg='white', relief='flat', 
                 padx=15, pady=5, cursor='hand2').pack(side='left', padx=5)
        tk.Button(nav_frame, text="В конец ⏭", command=lambda: self.navigate(self.total_pages), 
                 font=("Segoe UI", 10, "bold"), bg='#4CAF50', fg='white', relief='flat', 
                 padx=15, pady=5, cursor='hand2').pack(side='left', padx=5)
        
        tk.Frame(nav_frame, bg='#555555', width=2).pack(side='left', padx=10, fill='y')
        
        tk.Button(nav_frame, text="-5", command=lambda: self.navigate(-5), 
                 font=("Segoe UI", 10), bg='#FF9800', fg='white', relief='flat', 
                 padx=10, pady=5, cursor='hand2').pack(side='left', padx=5)
        tk.Button(nav_frame, text="+5", command=lambda: self.navigate(5), 
                 font=("Segoe UI", 10), bg='#FF9800', fg='white', relief='flat', 
                 padx=10, pady=5, cursor='hand2').pack(side='left', padx=5)
        
        self.info_label = tk.Label(nav_frame, text="", font=("Segoe UI", 10), bg='#2d2d2d', fg='cyan', anchor='w')
        self.info_label.pack(side='left', padx=10, fill='x', expand=True)
        # =========================
        
        self.result = None
        self.chunk_size = 2500
        self.current_page = 0
        self.total_pages = 0
        self.visible_charts = 2
        self._drag_start_x = None
        self._drag_start_page = None
        
        self.canvas.get_tk_widget().bind('<MouseWheel>', self.on_mouse_wheel)
        self.canvas.get_tk_widget().bind('<Button-4>', self.on_mouse_wheel)
        self.canvas.get_tk_widget().bind('<Button-5>', self.on_mouse_wheel)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_press_event', self.on_overview_click)

    def update(self, result):
        # 🟢 1. ГАРАНТИРОВАННАЯ НОРМАЛИЗАЦИЯ ДАННЫХ
        # Превращаем всё в DataFrame с одной колонкой 'values'
        if hasattr(result, 'columns') and 'values' in result.columns:
            self.result = result
        elif hasattr(result, 'values'): # numpy array или pandas Series
            flat_data = result.flatten() if hasattr(result, 'flatten') else result
            self.result = pd.DataFrame({'values': flat_data})
        else: # обычный список
            self.result = pd.DataFrame({'values': result})
            
        self.total_pages = (len(self.result) + self.chunk_size - 1) // self.chunk_size
        self.current_page = 0
        
        # === 2. ОТРИСОВКА OVERVIEW ===
        self.ax_overview.clear()
        setup_axis_strong(self.ax_overview, labelsize=8)
        
        # Рисуем только колонку 'values'
        self.result['values'].plot(ax=self.ax_overview, color='#0066cc', linewidth=0.5)
        self.ax_overview.set_title('Общий график ECG (кликните для перехода)')
        self.ax_overview.set_xlabel('Индекс')
        self.ax_overview.set_ylabel('Значение')
        
        # 🟢 3. БЕЗОПАСНЫЙ РАСЧЕТ ГРАНИЦ (явное приведение к float)
        y_min = float(self.result['values'].min())
        y_max = float(self.result['values'].max())
        margin = (y_max - y_min) * 0.1
        self.ax_overview.set_ylim(y_min - margin, y_max + margin)
        
        self._redraw_all()

    def _redraw_all(self):
        if self.result is None: return
        self._update_overview_rect()
        for i, ax in enumerate([self.ax_detail1, self.ax_detail2]):
            page_idx = self.current_page + i
            if page_idx < self.total_pages:
                self._update_detail_chart(ax, page_idx)
            else:
                ax.clear()
                setup_axis_strong(ax, 11)
                ax.set_xticks([])
                ax.set_yticks([])
                start_idx = page_idx * self.chunk_size
                ax.set_xlim(start_idx, start_idx + self.chunk_size)
                # 🟢 Безопасный расчет для пустых графиков
                y_min = float(self.result['values'].min())
                y_max = float(self.result['values'].max())
                ax.set_ylim(y_min - (y_max - y_min)*0.05, y_max + (y_max - y_min)*0.05)
        
        start_idx = self.current_page * self.chunk_size
        end_idx = min((self.current_page + self.visible_charts) * self.chunk_size, len(self.result))
        self.info_label.config(text=f'Страницы: {self.current_page + 1}-{min(self.current_page + self.visible_charts, self.total_pages)}/{self.total_pages} | Индексы: {start_idx} – {end_idx-1} | Всего точек: {len(self.result):,}')
        self.canvas.draw()

    def _update_detail_chart(self, ax, page_idx):
        start_idx = page_idx * self.chunk_size
        end_idx = min(start_idx + self.chunk_size, len(self.result))
        ax.clear()
        setup_axis_strong(ax, 11)
        
        # 🟢 Рисуем только 1D серию 'values'
        self.result['values'].iloc[start_idx:end_idx].plot(ax=ax, color='#0066cc', linewidth=0.8)
        
        # 🟢 Безопасный расчет границ
        y_min = float(self.result['values'].min())
        y_max = float(self.result['values'].max())
        margin = (y_max - y_min) * 0.05
        ax.set_ylim(y_min - margin, y_max + margin)
        ax.set_xlim(start_idx, start_idx + self.chunk_size)
        ax.set_title(f'Часть {page_idx + 1}/{self.total_pages}: индексы {start_idx} – {end_idx-1}')
        ax.set_xlabel('Индекс')
        ax.set_ylabel('Значение')

    def _update_overview_rect(self):
        for patch in self.ax_overview.patches: 
            patch.remove()
        for i in range(self.visible_charts):
            page_idx = self.current_page + i
            if page_idx < self.total_pages:
                start_idx = page_idx * self.chunk_size
                end_idx = min(start_idx + self.chunk_size, len(self.result))
                self.ax_overview.axvspan(start_idx, end_idx, alpha=0.4 if i == 0 else 0.2, color='red' if i == 0 else 'orange')

    # --- Навигация ---
    def navigate(self, delta):
        if self.result is None: return
        new_page = self.current_page + delta
        max_page = max(0, self.total_pages - self.visible_charts)
        self.current_page = max(0, min(new_page, max_page))
        self._redraw_all()

    def on_mouse_wheel(self, event):
        if self.result is None: return
        if event.delta > 0 or event.num == 4: self.navigate(-1)
        elif event.delta < 0 or event.num == 5: self.navigate(1)

    def on_overview_click(self, event):
        if self.result is None or event.inaxes != self.ax_overview or event.button != 1: return
        if event.xdata is None: return
        page_idx = int(event.xdata / self.chunk_size)
        max_page = max(0, self.total_pages - self.visible_charts)
        self.current_page = max(0, min(page_idx, max_page))
        self._redraw_all()

    def on_press(self, event):
        if event.button == 1 and event.inaxes is not None and event.inaxes != self.ax_overview:
            self._drag_start_x = event.xdata
            self._drag_start_page = self.current_page

    def on_release(self, event):
        self._drag_start_x = None
        self._drag_start_page = None

    def on_motion(self, event):
        if self._drag_start_x is None or event.xdata is None: return
        pages_to_move = int((self._drag_start_x - event.xdata) / self.chunk_size)
        if pages_to_move != 0:
            new_page = self._drag_start_page + pages_to_move
            max_page = max(0, self.total_pages - self.visible_charts)
            self.current_page = max(0, min(new_page, max_page))
            self._redraw_all()