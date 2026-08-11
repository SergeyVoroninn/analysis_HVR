import pandas as pd
import numpy as np

def parse_teamlogger_h10(path):
    """Парсинг сырого файла .teamloggerh10"""
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f if l.strip()]

    header = {}
    ecg_rows = []
    rr_vals = None
    acc_vals = None

    section = None
    for line in lines:
        if line.startswith('[Header]'):
            section = 'header'
            continue
        elif line.startswith('[ECG]'):
            section = 'ecg'
            continue
        elif line.startswith('[RR]'):
            section = 'rr'
            continue
        elif line.startswith('[ACC]'):
            section = 'acc'
            continue

        if section == 'header':
            if '=' in line:
                k, v = line.split('=', 1)
                header[k.strip()] = v.strip()
        elif section == 'ecg':
            if ':' in line:
                ts, vals_str = line.split(':', 1)
                vals = [int(x) for x in vals_str.split(',') if x.strip()]
                ecg_rows.append({'id': int(ts), 'values': vals})
        elif section == 'rr':
            rr_vals = [float(x) for x in line.split(',') if x.strip()]
        elif section == 'acc':
            acc_vals = [int(x) for x in line.split(',') if x.strip()]

    df_ecg = pd.DataFrame(ecg_rows)
    if not df_ecg.empty:
        expanded = df_ecg['values'].apply(pd.Series)
        expanded.columns = [f'ecg_{i}' for i in range(expanded.shape[1])]
        df_ecg = df_ecg[['id']].join(expanded)

    df_rr = pd.DataFrame({'rr_ms': rr_vals}) if rr_vals is not None else None
    df_acc = pd.DataFrame({'acc_raw': acc_vals}) if acc_vals is not None else None

    return header, df_ecg, df_rr, df_acc


def process_ecg_data(df_ecg):
    """Нормализация и подготовка ECG данных к отображению"""
    if df_ecg is None or df_ecg.empty:
        raise ValueError("Данные ECG пусты или отсутствуют в файле")
    
    # Создаем копию, чтобы избежать SettingWithCopyWarning в pandas
    df = df_ecg.copy()
    cols = df.columns[1:]
    df[cols] = df[cols].astype(float)
    
    # Нормализация (Z-score)
    df[cols] = (df[cols] - df[cols].mean()) / df[cols].std()
    df = df.sort_values('id')
    
    # Преобразование в 1D массив (Series)
    values_1d = df.drop(columns=['id']).values.ravel()
    return pd.Series(values_1d, name='value')


def load_and_process_teamlogger(file_path):
    """
    Главная функция модуля: загружает файл и возвращает полностью готовые данные.
    Возвращает кортеж: (result_series, df_rr, df_acc, header)
    """
    header, df_ecg, df_rr, df_acc = parse_teamlogger_h10(file_path)
    result = process_ecg_data(df_ecg)
    return result, df_rr, df_acc, header