"""
importer.py — импорт записей Polar H10 в БД.
"""
import uuid
import datetime
import os

from tkinter import messagebox, filedialog

from database import get_db_path
from models import get_session, Athlete, ECGRecord, ECGRaw
from analysis import parse_rr, calc_metrics, calc_stress, filter_rr, compute_psd

# ИМПОРТ НОВЫХ ФУНКЦИЙ БИОМЕТРИИ
from ecg_biometrics import check_ownership_with_saved_template, get_saved_template


def _parse_header(raw):
    dt_str, polar = None, None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("datetime="):
            dt_str = line.split("=", 1)[1]
        elif line.startswith("polar_id="):
            polar = line.split("=", 1)[1]
    return dt_str, polar


def _import_one(db_path, path, athletes, selected_athlete, status_cb, interactive=True, parent_window=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        if interactive:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
        return "err", None

    dt_str, polar = _parse_header(raw)
    try:
        dt = datetime.datetime.strptime(dt_str, "%Y.%m.%d %H:%M:%S")
    except Exception:
        dt = datetime.datetime.now().replace(microsecond=0)
    recorded_at = dt.isoformat(sep=" ")

    session = get_session(db_path)
    try:
        existing = (session.query(ECGRecord)
                    .filter(ECGRecord.recorded_at == recorded_at)
                    .first())
        if existing:
            return "dup", None

        athlete = next((a for a in athletes if a[5] == polar), None)
        if athlete is None:
            if not selected_athlete:
                return "skip", None
            athlete = selected_athlete

        aid = athlete[0]
        
        # ⚡ НОВОЕ: БИОМЕТРИЧЕСКАЯ ПРОВЕРКА ПЕРЕД ИМПОРТОМ (по сохраненному шаблону)
        if interactive and parent_window:
            status, distance, prob = check_ownership_with_saved_template(db_path, aid, path)
            
            if status == "NO_TEMPLATE":
                if not messagebox.askyesno("Биометрия", 
                    "Для этого атлета еще не создан биометрический шаблон.\n"
                    "Рекомендуется создать его в списке записей атлета.\n\n"
                    "Продолжить импорт?", parent=parent_window, icon='info'):
                    return "cancelled", None
                    
            elif status == "SUSPICIOUS":
                msg = (
                    f"🚨 ВНИМАНИЕ: Низкое биометрическое сходство!\n\n"
                    f"Индекс различия: {distance:.3f} (порог: 0.30)\n"
                    f"Вероятность совпадения: {prob*100:.1f}%\n\n"
                    f"Эта запись, скорее всего, принадлежит ДРУГОМУ человеку.\n"
                    f"Вы уверены, что хотите импортировать её этому атлету?"
                )
                if not messagebox.askyesno("Проверка принадлежности", msg, parent=parent_window, icon='warning'):
                    return "cancelled", None
                    
            elif status == "LOW_CONFIDENCE":
                messagebox.showinfo("Биометрия", 
                    f"ℹ️ Запись распознана с умеренной уверенностью ({prob*100:.1f}%).\n"
                    f"Рекомендуется проверить правильность выбора атлета.", 
                    parent=parent_window, icon='info')

        rr = parse_rr(raw)
        seq = filter_rr(rr) if rr else [] 

        m = calc_metrics(seq) if seq else None
        s = calc_stress(seq) if seq else None
        duration = sum(rr) / 1000.0 if rr else 0.0

        spectral_tp = None
        if seq and len(seq) >= 3:
            try:
                _, _, bands = compute_psd(seq)
                spectral_tp = bands.get("tp")
            except Exception:
                spectral_tp = None

        rec = ECGRecord(
            athlete_id=aid,
            recorded_at=recorded_at,
            duration_seconds=duration,
            # profile="import",  <-- УДАЛЕНО, так как поля больше нет в models.py
            mean_hr=m["mean_hr"] if m else None,
            rmssd=m["rmssd"] if m else None,
            sdnn=m["sdnn"] if m else None,
            status=m["status"] if m else "ok",
            stress_si=s["si"] if s else None,
            tp=spectral_tp,
        )
        session.add(rec)
        session.flush()
        rec.raw = ECGRaw(record_id=rec.id, raw_data=raw)
        session.commit()
    except Exception as e:
        session.rollback()
        if interactive:
            messagebox.showerror("Ошибка", f"Не удалось сохранить запись:\n{e}")
        return "err", None
    finally:
        session.close()

    if interactive and status_cb:
        status_cb(f"Запись добавлена: {dt:%d.%m.%Y %H:%M}")
    return "added", aid


def import_ecg(parent, db_path, athletes, selected_athlete, status_cb):
    """Диалог выбора файлов и пакетный импорт."""
    paths = filedialog.askopenfilenames(
        title="Выберите файлы записей ЭКГ (Ctrl/Shift — несколько)",
        filetypes=[("Polar H10", "*.teamloggerh10"), ("Все файлы", "*.*")])
    if not paths:
        return None
    paths = list(paths)
    changed_aid = None

    if len(paths) == 1:
        status, changed_aid = _import_one(db_path, paths[0], athletes,
                                          selected_athlete, status_cb, 
                                          interactive=True, parent_window=parent)
        return changed_aid

    # Пакетный импорт без биометрических проверок (чтобы не блокировать UI)
    stats = {"added": 0, "dup": 0, "skip": 0, "err": 0, "cancelled": 0}
    for p in paths:
        s, aid = _import_one(db_path, p, athletes,
                             selected_athlete, None, interactive=False, parent_window=None)
        stats[s] = stats.get(s, 0) + 1
        if aid:
            changed_aid = aid
        total = sum(stats.values())
        if total % 10 == 0 or total == len(paths):
            status_cb(f"Импорт... {total}/{len(paths)}")

    status_cb(f"Импорт: {stats['added']} доб., {stats['dup']} дубл., "
              f"{stats['skip']} проп., {stats['err']} ош.")
    return changed_aid