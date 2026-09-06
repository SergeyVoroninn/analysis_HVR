"""
debug_plot.py — визуальная отладка расхождений в метриках HRV.
Отрисовывает ЭКГ, RR-интервалы и мгновенную ЧСС для выбранного эталона.
"""
import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt

# Добавляем корневую папку проекта в путь, чтобы импортировать analysis
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import analysis as hrv

# ==============================================================================
# НАСТРОЙКИ: измените эту переменную, чтобы посмотреть другой файл
# ==============================================================================
TARGET_FILE = "C821E528_2026_08_05_09_09_30_teamloggerh10.teamloggerh10"
# TARGET_FILE = "C821E528_2026_08_08_09_17_03_teamloggerh10.teamloggerh10" # Филипп
# ==============================================================================

def main():
    etalons_path = os.path.join(os.path.dirname(__file__), "etalons.json")
    
    # 1. Загрузка эталона
    with open(etalons_path, "r", encoding="utf-8") as f:
        # Обработка возможного BOM
        content = f.read().encode('utf-8')
        if content.startswith(b'\xef\xbb\xbf'):
            content = content[3:]
        etalons = json.loads(content.decode('utf-8'))

    target_etalon = next((e for e in etalons if TARGET_FILE in e["file"]), None)
    if not target_etalon:
        print(f"❌ Ошибка: Эталон для '{TARGET_FILE}' не найден в etalons.json")
        return

    raw_file_path = target_etalon["file"]
    if not os.path.isabs(raw_file_path):
        raw_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", raw_file_path))

    if not os.path.exists(raw_file_path):
        print(f"❌ Ошибка: Файл данных не найден: {raw_file_path}")
        return

    print(f"📂 Загрузка данных: {os.path.basename(raw_file_path)}")
    with open(raw_file_path, "r", encoding="utf-8") as f:
        raw_data = f.read()

    # 2. Парсинг данных
    rr_raw = hrv.parse_rr(raw_data)
    rr_filt = hrv.filter_rr(rr_raw)
    ecg_samples = hrv.parse_ecg(raw_data)
    
    print(f"✅ Загружено: {len(rr_raw)} RR-интервалов, {len(ecg_samples)} семплов ЭКГ.")

    # 3. Подготовка данных для графиков
    # Временная ось (в секундах)
    time_raw = np.cumsum(rr_raw) / 1000.0
    time_filt = np.cumsum(rr_filt) / 1000.0
    
    # Мгновенная ЧСС (уд/мин)
    hr_raw = 60000.0 / np.array(rr_raw)
    hr_filt = 60000.0 / np.array(rr_filt)

    # 4. Построение графиков
    fig, (ax_ecg, ax_rr, ax_hr) = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
    fig.suptitle(f"Отладка HRV: {TARGET_FILE}", fontsize=14, fontweight='bold')

    # --- График 1: Фрагмент ЭКГ (первые 5 секунд) ---
    # Предполагаем частоту дискретизации ~250 Гц (стандарт для таких устройств). 
    # 5 секунд = 1250 семплов. Если частота другая, масштаб просто сожмется/растянется.
    ecg_plot_len = min(1500, len(ecg_samples)) 
    ax_ecg.plot(ecg_samples[:ecg_plot_len], color='blue', linewidth=0.8)
    ax_ecg.set_title("Сырой сигнал ЭКГ (первые ~5 секунд)")
    ax_ecg.set_ylabel("Амплитуда")
    ax_ecg.grid(True, alpha=0.3)

    # --- График 2: Тахограмма RR (Сырые vs Отфильтрованные) ---
    ax_rr.plot(time_raw, rr_raw, label='Raw RR', alpha=0.4, marker='.', markersize=3, color='gray')
    ax_rr.plot(time_filt, rr_filt, label='Filtered RR', color='red', linewidth=1.5)
    ax_rr.set_title("Тахограмма RR-интервалов (Серые точки = сырые, Красная линия = после filter_rr)")
    ax_rr.set_ylabel("RR (мс)")
    ax_rr.legend(loc='upper right')
    ax_rr.grid(True, alpha=0.3)

    # --- График 3: Мгновенная ЧСС ---
    ax_hr.plot(time_raw, hr_raw, label='Raw HR', alpha=0.4, marker='.', markersize=3, color='gray')
    ax_hr.plot(time_filt, hr_filt, label='Filtered HR', color='green', linewidth=1.5)
    ax_hr.set_title("Мгновенная частота сердечных сокращений (ЧСС)")
    ax_hr.set_xlabel("Время (секунды)")
    ax_hr.set_ylabel("ЧСС (уд/мин)")
    ax_hr.legend(loc='upper right')
    ax_hr.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    # 5. Вывод метрик в консоль для сверки
    print("\n" + "="*60)
    print("📊 РАССЧИТАННЫЕ МЕТРИКИ (после filter_rr):")
    print("="*60)
    metrics = hrv.calc_metrics(rr_filt)
    stress = hrv.calc_stress(rr_filt)
    
    if metrics:
        print(f"Mean HR : {metrics['mean_hr']:>6.1f} уд/мин")
        print(f"SDNN    : {metrics['sdnn']:>6.1f} мс")
        print(f"RMSSD   : {metrics['rmssd']:>6.1f} мс")
    if stress:
        print(f"Mo      : {stress['mo_ms']:>6.1f} мс")
        print(f"SI (Стресс) : {stress['si']:>6.1f} у.е.")
    
    print("="*60)
    print("📈 Отображение графиков... (закройте окно для завершения)")
    
    # Показываем графики
    plt.show()

if __name__ == "__main__":
    # Проверка наличия matplotlib
    try:
        import matplotlib
    except ImportError:
        print("❌ Ошибка: Не установлена библиотека matplotlib.")
        print("Установите её командой: pip install matplotlib")
        sys.exit(1)
    
    main()