import time
import math
import random

def create_record(device='C8208E2E', datetime=None, duration_seconds=12.0):
    if datetime is None:
        datetime = time.strftime("%Y.%m.%d %H:%M:%S", time.localtime())
        
    header = f"""TeamLoggerH10Data
[Header]
version=1.0
datetime={datetime}
polar_id={device}"""

    ecg_header = '[ECG]'
    ecg_data = create_ecg(duration_seconds)
    
    rr_header = '[RR]'
    rr_data = create_rr(duration_seconds)
    
    acc_header = '[ACC]'
    acc_data = create_acc(duration_seconds)

    output_data = '\n'.join([header, ecg_header, ecg_data, rr_header, rr_data, acc_header, acc_data])
    return output_data

def create_ecg(duration_seconds):
    """
    Генерирует реалистичный многострочный ЭКГ-сигнал на основе паттерна Polar H10.
    Включает стартовый переходный процесс и анатомически точный комплекс QRS.
    """
    polar_epoch = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, 0))
    start_timestamp = int((time.time() - polar_epoch) * 1e9)
    
    total_samples = int(duration_seconds * 130)
    samples_per_row = 73
    ns_per_row = int((samples_per_row / 130.0) * 1e9)
    
    ecg_rows = []
    current_timestamp = start_timestamp
    
    # Моделирование стабильного положения сердца (интервал ~115 отсчетов между ударами)
    heart_rate_period = 115 
    
    for row_idx in range(math.ceil(total_samples / samples_per_row)):
        row_values = []
        
        # Определяем сколько элементов писать в текущую строку (последняя может быть короче)
        remaining_samples = total_samples - (row_idx * samples_per_row)
        current_row_samples = min(samples_per_row, remaining_samples)
        
        for s in range(current_row_samples):
            global_idx = row_idx * samples_per_row + s
            
            # 1. Симуляция стартового переходного процесса (первые ~150 точек)
            if global_idx < 146:
                # Плавное нелинейное падение от 13148 до нормы
                progress = global_idx / 146
                baseline = int(13148 * (1 - progress)**2 + (-150) * progress)
            else:
                # Обычный дрейф изолинии здорового человека с дыхательным шагом
                baseline = int(-200 + 80 * math.sin(global_idx * 0.05) + random.randint(-15, 15))
            
            # 2. Математическая модель сердцебиения (Комплекс P-Q-R-S-T)
            phase = global_idx % heart_rate_period
            heart_wave = 0
            
            if global_idx > 40: # Не бьем во время экстремального старта
                if 0 <= phase < 8:    # Зубец P (небольшой подъем)
                    heart_wave = 150 * math.sin(phase * (math.pi / 8))
                elif 10 <= phase < 14: # Зубец Q (микро-провал перед взлетом)
                    heart_wave = -150 * math.sin((phase - 10) * (math.pi / 4))
                elif 14 <= phase < 19: # Зубец R (Мощный главный пик вверх)
                    heart_wave = 1300 * math.sin((phase - 14) * (math.pi / 5))
                elif 19 <= phase < 25: # Зубец S (Глубокий провал вниз)
                    heart_wave = -1400 * math.sin((phase - 19) * (math.pi / 6))
                elif 35 <= phase < 55: # Зубец T (Восстановление желудочков)
                    heart_wave = 350 * math.sin((phase - 35) * (math.pi / 20))
            
            val = int(baseline + heart_wave)
            row_values.append(str(val))
            
        # Формируем строку. Если строка полная (73 шт) — ставим в конце запятую и перенос.
        if current_row_samples == samples_per_row:
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)},")
        else:
            # Для финального кусочка (как ваши "59" в конце)
            ecg_rows.append(f"{current_timestamp}:{','.join(row_values)}")
            
        current_timestamp += ns_per_row
        
    return "\n".join(ecg_rows)

def create_rr(duration_seconds):
    """Генерирует сплошной массив RR-интервалов."""
    intervals = []
    accumulated_time_ms = 0
    target_time_ms = duration_seconds * 1000
    while accumulated_time_ms < target_time_ms:
        next_rr = random.randint(860, 910) # Соответствует периоду ~115 отсчетов ЭКГ
        intervals.append(str(next_rr))
        accumulated_time_ms += next_rr
    return ",".join(intervals)

def create_acc(duration_seconds):
    """Генерирует плоский массив ACC (200 Гц)."""
    count = int(duration_seconds * 200)
    acc_samples = [str(int(31500 + random.randint(-300, 300))) for _ in range(count)]
    return ",".join(acc_samples)

if __name__ == '__main__':
    # Генерируем лог на 12 секунд (чтобы сымитировать объем вашей выгрузки)
    log_content = create_record(duration_seconds=300.0)
    
    filename = "polar_h10_syn_record.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(log_content)
        
