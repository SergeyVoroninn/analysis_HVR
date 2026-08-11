import tkinter as tk
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from matplotlib.patches import Wedge
from utils import setup_axis_strong

class QualityTab:
    def __init__(self, parent_notebook):
        self.frame = tk.Frame(parent_notebook, bg='#1e1e1e')
        parent_notebook.add(self.frame, text="  Качество ECG  ")
        
        container = tk.Frame(self.frame, bg='#1e1e1e')
        container.pack(fill='both', expand=True)
        
        self.fig = Figure(facecolor='#1e1e1e', figsize=(16, 10))
        gs = gridspec.GridSpec(3, 2, figure=self.fig, hspace=0.4, wspace=0.3)
        
        self.ax_overview = self.fig.add_subplot(gs[0, :])
        self.ax_histogram = self.fig.add_subplot(gs[1, 0])
        self.ax_noise = self.fig.add_subplot(gs[1, 1])
        self.ax_baseline = self.fig.add_subplot(gs[2, 0])
        self.ax_score = self.fig.add_subplot(gs[2, 1])
        self.fig.subplots_adjust(left=0.1, right=0.95, top=0.95, bottom=0.1)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        self.info_label = tk.Label(self.frame, text="Анализ качества отобразится после загрузки файла", 
                                   font=("Segoe UI", 10), bg='#2d2d2d', fg='cyan', anchor='w', padx=20)
        self.info_label.pack(fill='x', padx=10, pady=(5, 0))

    def analyze_quality(self, signal):
        n = len(signal)
        mean_val, std_val = np.mean(signal), np.std(signal)
        artifacts = np.abs(signal - mean_val) > (mean_val + 3 * std_val)
        artifact_pct = (np.sum(artifacts) / n) * 100
        
        noise_level = np.std(np.diff(signal))
        baseline = pd.Series(signal).rolling(500, center=True, min_periods=1).mean().values
        baseline_drift = np.std(baseline - mean_val)
        
        snr = 10 * np.log10(np.var(signal) / (np.var(np.diff(signal)) / 2)) if np.var(np.diff(signal)) > 0 else 0
        score = max(0, min(100, max(0, 40 - artifact_pct * 2) + max(0, 30 - noise_level * 0.5) + max(0, 20 - baseline_drift * 0.3) + min(10, snr / 5)))
        
        if score >= 80: rec, color = "✅ ОТЛИЧНО - Данные готовы к анализу", '#4CAF50'
        elif score >= 60: rec, color = "⚠️ ХОРОШО - Небольшие артефакты", '#FFC107'
        elif score >= 40: rec, color = "⚠️ УДОВЛЕТВОРИТЕЛЬНО - Рекомендуется переснять", '#FF9800'
        else: rec, color = "❌ ПЛОХО - Необходимо переснять запись", '#F44336'
        
        return {'artifact_pct': round(artifact_pct, 2), 'noise': round(noise_level, 3), 'drift': round(baseline_drift, 3),
                'snr': round(snr, 2), 'score': round(score, 1), 'rec': rec, 'color': color, 'artifacts': artifacts, 'baseline': baseline}

    def update(self, result):
        for ax in self.fig.axes: ax.clear()
        if result is None:
            self.info_label.config(text="Данные ECG отсутствуют", fg='orange')
            for ax in self.fig.axes:
                ax.set_facecolor('#2d2d2d'); ax.text(0.5, 0.5, 'Нет данных', ha='center', va='center', fontsize=14, color='gray', transform=ax.transAxes)
                ax.set_xticks([]); ax.set_yticks([])
            self.canvas.draw(); return

            # 🟢 ИСПРАВЛЕНИЕ: Правильно извлекаем 1D массив из DataFrame
        if isinstance(result, pd.DataFrame) and 'values' in result.columns:
            ecg_data = result['values'].values  # Берем конкретную колонку как 1D массив
        else:
            ecg_data = result.values.flatten() if hasattr(result, 'values') else result
                
        metrics = self.analyze_quality(ecg_data)
        
        signal = result.values

        setup_axis_strong(self.ax_overview, 10)
        self.ax_overview.plot(signal, color='#0066cc', linewidth=0.5, alpha=0.7)
        idx = np.where(metrics['artifacts'])[0]
        if len(idx) > 0: self.ax_overview.scatter(idx, signal[idx], color='red', s=1, alpha=0.5, label='Артефакты')
        self.ax_overview.axhline(y=0, color='gray', linewidth=0.5, linestyle='--')
        self.ax_overview.set_title('ECG сигнал с подсветкой артефактов'); self.ax_overview.set_xlabel('Индекс'); self.ax_overview.set_ylabel('Значение'); self.ax_overview.legend()

        setup_axis_strong(self.ax_histogram, 10)
        self.ax_histogram.hist(signal, bins=50, color='#4c72b0', alpha=0.7, edgecolor='black')
        self.ax_histogram.axvline(x=np.mean(signal), color='red', linewidth=2, label=f'Среднее: {np.mean(signal):.2f}')
        self.ax_histogram.axvline(x=np.mean(signal) + 3*np.std(signal), color='orange', linewidth=2, linestyle='--', label='Порог')
        self.ax_histogram.axvline(x=np.mean(signal) - 3*np.std(signal), color='orange', linewidth=2, linestyle='--')
        self.ax_histogram.set_title('Распределение амплитуд'); self.ax_histogram.set_xlabel('Значение'); self.ax_histogram.set_ylabel('Частота'); self.ax_histogram.legend()

        setup_axis_strong(self.ax_noise, 10)
        self.ax_noise.plot(np.diff(signal)[:10000], color='purple', linewidth=0.5, alpha=0.7)
        self.ax_noise.axhline(y=0, color='gray', linewidth=0.5, linestyle='--')
        self.ax_noise.set_title('Высокочастотный шум'); self.ax_noise.set_xlabel('Индекс'); self.ax_noise.set_ylabel('ΔЗначение')

        setup_axis_strong(self.ax_baseline, 10)
        self.ax_baseline.plot(signal[:10000], color='#0066cc', linewidth=0.5, alpha=0.5, label='Сигнал')
        self.ax_baseline.plot(metrics['baseline'][:10000], color='orange', linewidth=2, label='Базовая линия')
        self.ax_baseline.set_title('Дрейф базовой линии'); self.ax_baseline.set_xlabel('Индекс'); self.ax_baseline.set_ylabel('Значение'); self.ax_baseline.legend()

        setup_axis_strong(self.ax_score, 10)
        self.ax_score.axis('off')
        self.ax_score.add_patch(plt.Circle((0.5, 0.5), 0.3, transform=self.ax_score.transAxes, fill=False, color='gray', linewidth=3))
        self.ax_score.add_patch(Wedge((0.5, 0.5), 0.3, 90, 90 - metrics['score'] * 3.6, transform=self.ax_score.transAxes, facecolor=metrics['color'], alpha=0.7))
        self.ax_score.text(0.5, 0.5, f'{metrics["score"]:.0f}', ha='center', va='center', fontsize=24, fontweight='bold', color=metrics['color'], transform=self.ax_score.transAxes)
        self.ax_score.text(0.5, 0.2, 'Качество', ha='center', va='center', fontsize=12, color='#e0e0e0', transform=self.ax_score.transAxes)
        self.ax_score.text(0.05, 0.5, f"Артефакты: {metrics['artifact_pct']}%\nШум: {metrics['noise']}\nSNR: {metrics['snr']} дБ\nДрейф: {metrics['drift']}", ha='left', va='center', fontsize=10, color='#e0e0e0', transform=self.ax_score.transAxes, family='monospace')

        self.info_label.config(text=f"{metrics['rec']} | Качество: {metrics['score']}/100 | Артефакты: {metrics['artifact_pct']}% | SNR: {metrics['snr']} дБ", fg=metrics['color'], font=('Segoe UI', 11, 'bold'))
        self.canvas.draw()