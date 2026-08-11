import tkinter as tk
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse
from utils import setup_axis_strong

class RrTab:
    def __init__(self, parent_notebook):
        self.frame = tk.Frame(parent_notebook, bg='#1e1e1e')
        parent_notebook.add(self.frame, text="  RR (Стресс)  ")
        
        container = tk.Frame(self.frame, bg='#1e1e1e')
        container.pack(fill='both', expand=True)
        
        self.fig = Figure(facecolor='#1e1e1e')
        self.ax_poincare = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.12, right=0.95, top=0.90, bottom=0.12)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        self.info_label = tk.Label(self.frame, text="Данные RR отобразятся после загрузки файла", 
                                   font=("Segoe UI", 10), bg='#2d2d2d', fg='cyan', anchor='w', padx=20)
        self.info_label.pack(fill='x', padx=10, pady=(5, 0))

    def _get_stress_info(self, idx):
        if idx < 30: return '#4CAF50', 'НИЗКИЙ (хорошо)'
        elif idx < 70: return '#FFC107', 'СРЕДНИЙ'
        else: return '#F44336', 'ВЫСОКИЙ (тревога!)'

    def update(self, df_rr):
        self.ax_poincare.clear()
        for ax in list(self.fig.axes):
            if ax != self.ax_poincare: self.fig.delaxes(ax)
        
        if df_rr is None or df_rr.empty or 'rr_ms' not in df_rr.columns:
            self.info_label.config(text="Данные RR отсутствуют в файле", fg='orange')
            self.ax_poincare.set_facecolor('#2d2d2d')
            self.ax_poincare.text(0.5, 0.5, 'Нет данных RR', ha='center', va='center', fontsize=14, color='gray', transform=self.ax_poincare.transAxes)
            self.ax_poincare.set_xticks([]); self.ax_poincare.set_yticks([])
            self.canvas.draw(); return

        rr = df_rr['rr_ms'].dropna().values
        if len(rr) < 2:
            self.info_label.config(text="Недостаточно данных для анализа", fg='orange'); return

        rr_n, rr_np1 = rr[:-1], rr[1:]
        sd1 = np.std(rr_np1 - rr_n) / np.sqrt(2)
        sd2 = np.std(rr_np1 + rr_n) / np.sqrt(2)
        sdnn = np.std(rr)
        rmssd = np.sqrt(np.mean(np.diff(rr)**2))
        ratio = sd1 / sd2 if sd2 != 0 else 0
        stress_idx = max(0, min(100, 100 - (sdnn / 1.5 + rmssd / 1.0)))
        
        setup_axis_strong(self.ax_poincare, 11)
        color, _ = self._get_stress_info(stress_idx)
        
        self.ax_poincare.scatter(rr_n, rr_np1, s=15, alpha=0.4, color=color, label=f'Точки: {len(rr_n)}')
        min_val, max_val = min(rr_n.min(), rr_np1.min()), max(rr_n.max(), rr_np1.max())
        self.ax_poincare.plot([min_val, max_val], [min_val, max_val], 'k--', linewidth=1, alpha=0.7, label='Линия равенства')
        
        cx, cy = np.mean(rr_n), np.mean(rr_np1)
        self.ax_poincare.add_patch(Ellipse((cx, cy), width=sd1*4, height=sd1*4, angle=135, fill=False, color='blue', linewidth=2, alpha=0.6, label=f'SD1={sd1:.2f} мс'))
        self.ax_poincare.add_patch(Ellipse((cx, cy), width=sd2*4, height=sd2*4, angle=45, fill=False, color='red', linewidth=2, alpha=0.6, label=f'SD2={sd2:.2f} мс'))
        
        self.ax_poincare.set_xlabel('RR(n), мс', fontsize=11); self.ax_poincare.set_ylabel('RR(n+1), мс', fontsize=11)
        self.ax_poincare.set_title('Poincaré-график RR-интервалов', fontsize=12, fontweight='bold')
        self.ax_poincare.grid(True, linestyle=':', alpha=0.5, color='#444444'); self.ax_poincare.set_aspect('equal'); self.ax_poincare.legend(loc='upper left', fontsize=9)
        
        ax_stress = self.fig.add_axes([0.12, 0.02, 0.76, 0.06])
        ax_stress.set_xlim(0, 100); ax_stress.set_ylim(0, 1); ax_stress.axis('off')
        ax_stress.imshow(np.linspace(0, 1, 256).reshape(1, -1), aspect='auto', extent=[0, 100, 0, 1], cmap=plt.cm.RdYlGn_r)
        ax_stress.axvline(x=stress_idx, color='black', linewidth=2, alpha=0.8)
        ax_stress.text(stress_idx, 0.5, f'▼\n{stress_idx:.0f}', ha='center', va='center', fontsize=9, fontweight='bold', color='black', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.9))
        ax_stress.text(15, 1.15, 'Низкий\n(хорошо)', ha='center', fontsize=8, color='#4CAF50', fontweight='bold')
        ax_stress.text(50, 1.15, 'Средний', ha='center', fontsize=8, color='#FF9800', fontweight='bold')
        ax_stress.text(85, 1.15, 'Высокий\n(стресс)', ha='center', fontsize=8, color='#F44336', fontweight='bold')
        
        _, label = self._get_stress_info(stress_idx)
        self.info_label.config(text=f"ИНДЕКС СТРЕССА: {stress_idx:.1f} — {label} | SD1: {sd1:.2f} мс | SD2: {sd2:.2f} мс | SD1/SD2: {ratio:.2f} | SDNN: {sdnn:.2f} мс | RMSSD: {rmssd:.2f} мс", fg=color, font=('Segoe UI', 10, 'bold'))
        self.canvas.draw()