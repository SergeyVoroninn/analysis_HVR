import tkinter as tk
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from scipy.interpolate import CubicSpline
from utils import setup_axis_strong

class HrvTab:
    def __init__(self, parent_notebook):
        self.frame = tk.Frame(parent_notebook, bg='#1e1e1e')
        parent_notebook.add(self.frame, text="  Спектр HRV  ")
        
        container = tk.Frame(self.frame, bg='#1e1e1e')
        container.pack(fill='both', expand=True)
        
        # Создаем фигуру с 3 графиками друг под другом
        self.fig = Figure(facecolor='#1e1e1e', figsize=(16, 12))
        gs = gridspec.GridSpec(3, 1, figure=self.fig, hspace=0.4)
        
        self.ax_rr_orig = self.fig.add_subplot(gs[0, 0])
        self.ax_rr_interp = self.fig.add_subplot(gs[1, 0])
        self.ax_psd = self.fig.add_subplot(gs[2, 0])
        
        self.fig.subplots_adjust(left=0.08, right=0.95, top=0.95, bottom=0.06)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        self.info_label = tk.Label(self.frame, text="Спектральный анализ отобразится после загрузки файла", 
                                   font=("Segoe UI", 10), bg='#2d2d2d', fg='cyan', anchor='w', padx=20)
        self.info_label.pack(fill='x', padx=10, pady=(5, 0))

    def update(self, df_rr):
        # Очистка всех осей перед новой отрисовкой
        for ax in self.fig.axes:
            ax.clear()
            
        # Безопасная проверка вместо assert
        if df_rr is None or df_rr.empty or 'rr_ms' not in df_rr.columns:
            self.info_label.config(text="Данные RR отсутствуют в файле", fg='orange')
            for ax in self.fig.axes:
                ax.set_facecolor('#2d2d2d')
                ax.text(0.5, 0.5, 'Нет данных RR', ha='center', va='center', fontsize=14, color='gray', transform=ax.transAxes)
                ax.set_xticks([])
                ax.set_yticks([])
            self.canvas.draw()
            return

        R_R = df_rr['rr_ms'].dropna().values
        
        if len(R_R) == 0:
            self.info_label.config(text="Данные RR пусты", fg='orange')
            self.canvas.draw()
            return
            
        if not np.all(R_R > 0):
            self.info_label.config(text="Обнаружены нулевые или отрицательные R-R интервалы (ошибка датчика/парсинга)", fg='red')
            self.canvas.draw()
            return

        # 1. Исходная кардиоинтервалограмма
        setup_axis_strong(self.ax_rr_orig, labelsize=10)
        x = np.arange(len(R_R))
        self.ax_rr_orig.plot(x, R_R, linewidth=1, color='#539ecd')
        self.ax_rr_orig.fill_between(x, R_R, color='#539ecd', alpha=0.4)
        self.ax_rr_orig.set_title('R-R Кардиоинтервалограмма (исходные интервалы)')
        self.ax_rr_orig.set_xlabel('№ интервала')
        self.ax_rr_orig.set_ylabel('Длительность интервала, мс')

        # 2. Интерполяция к равномерной сетке по времени
        R_R_sec = R_R / 1000.0
        time_steps = np.cumsum(R_R_sec)
        
        fs = 4.0  # целевая частота дискретизации 4 Гц
        new_time = np.arange(time_steps[0], time_steps[-1], 1/fs)
        
        spline_model = CubicSpline(time_steps, R_R_sec)
        R_R_interp = spline_model(new_time)
        
        setup_axis_strong(self.ax_rr_interp, labelsize=10)
        self.ax_rr_interp.plot(new_time, R_R_interp, linewidth=1, color='#539ecd')
        self.ax_rr_interp.fill_between(new_time, R_R_interp, color='#539ecd', alpha=0.4)
        self.ax_rr_interp.set_title(f'R-R Кардиоинтервалограмма (интерполировано, fs={fs} Гц)')
        self.ax_rr_interp.set_xlabel('Время, с')
        self.ax_rr_interp.set_ylabel('Длительность интервала, с')

        # 3. Спектральный анализ (FFT)
        R_R_centered = R_R_interp - np.mean(R_R_interp)
        N_interp = len(R_R_interp)
        R_R_spectral = np.fft.fft(R_R_centered)
        frequencies = np.fft.fftfreq(N_interp, d=1/fs)
        
        # Используем только положительные частоты
        pos_mask = frequencies > 0
        freq_pos = frequencies[pos_mask]
        spec_pos = R_R_spectral[pos_mask]
        
        # Нормализация PSD: стандартная формула для одностороннего спектра
        psd_sec = 2 * np.abs(spec_pos)**2 / (fs * N_interp)  # (с^2/Гц)
        psd = psd_sec * 1e6  # перевод в мс^2/Гц
        
        # Диапазоны частот (HRV стандарты)
        hf_mask = (freq_pos > 0.15) & (freq_pos <= 0.4)
        lf_mask = (freq_pos > 0.04) & (freq_pos <= 0.15)
        vlf_mask = (freq_pos > 0.003) & (freq_pos <= 0.04)
        ulf_mask = (freq_pos >= 0) & (freq_pos <= 0.003)
        
        # Интегрирование по диапазонам (площадь под кривой)
        hf = np.trapezoid(psd[hf_mask], freq_pos[hf_mask])
        lf = np.trapezoid(psd[lf_mask], freq_pos[lf_mask])
        vlf = np.trapezoid(psd[vlf_mask], freq_pos[vlf_mask])
        ulf = np.trapezoid(psd[ulf_mask], freq_pos[ulf_mask]) if ulf_mask.any() else 0.0
        
        TP = hf + lf + vlf + ulf
        lf_hf_ratio = lf / hf if hf > 0 else 0.0
        
        # График спектра
        setup_axis_strong(self.ax_psd, labelsize=10)
        self.ax_psd.plot(freq_pos, psd, linewidth=1, color='black', alpha=0.6)
        self.ax_psd.fill_between(freq_pos[hf_mask], psd[hf_mask], color="#48dc55", alpha=0.7, label=f'HF: {hf:.1f} мс²')
        self.ax_psd.fill_between(freq_pos[lf_mask], psd[lf_mask], color="#e0e720", alpha=0.7, label=f'LF: {lf:.1f} мс²')
        self.ax_psd.fill_between(freq_pos[vlf_mask], psd[vlf_mask], color="#d52626", alpha=0.7, label=f'VLF: {vlf:.1f} мс²')
        
        self.ax_psd.set_title('Спектр мощности R-R (PSD)')
        self.ax_psd.set_xlabel('Частота, Гц')
        self.ax_psd.set_ylabel('Мощность, мс²/Гц')
        self.ax_psd.legend(loc='upper right')
        self.ax_psd.set_xlim(0, 0.5)
        
        # === ДОБАВЛЕН ТЕКСТОВЫЙ БЛОК С МЕТРИКАМИ ПРЯМО НА ГРАФИК ===
        metrics_text = (
            f"HF  = {hf:.1f} мс²\n"
            f"LF  = {lf:.1f} мс²\n"
            f"VLF = {vlf:.1f} мс²\n"
            f"ULF = {ulf:.1f} мс²\n"
            f"TP  = {TP:.1f} мс²\n"
            f"LF/HF = {lf_hf_ratio:.2f}"
        )
        self.ax_psd.text(0.02, 0.98, metrics_text, 
                        transform=self.ax_psd.transAxes, 
                        fontsize=11, 
                        verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9),
                        family='monospace')
        # ============================================================
        
        # Обновление информационной строки
        duration_min = len(R_R_sec) / 60
        info_text = (
            f"Запись: {duration_min:.1f} мин | Интервалов: {len(R_R)}   |   "
            f"HF = {hf:.1f} мс²   |   LF = {lf:.1f} мс²   |   VLF = {vlf:.1f} мс²   |   "
            f"TP = {TP:.1f} мс²   |   LF/HF = {lf_hf_ratio:.2f}"
        )
        self.info_label.config(text=info_text, fg='#00ff00', font=('Segoe UI', 10, 'bold'))
        
        self.canvas.draw()