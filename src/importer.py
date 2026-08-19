"""
importer.py — импорт записей Polar H10 в БД (как в app.py).
"""
import uuid
import datetime

from tkinter import messagebox, filedialog

from database import get_db_path
from models import get_session, Athlete, ECGRecord, ECGRaw
from analysis import parse_rr, calc_metrics, calc_stress


def _parse_header(raw):
    dt_str, polar = None, None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("datetime="):
            dt_str = line.split("=", 1)[1]
        elif line.startswith("polar_id="):
            polar = line.split("=", 1)[1]
    return dt_str, polar


def _import_one(db_path, path, athletes, selected_athlete, status_cb, interactive=True):
    """status_cb(text) — вывод в статус-бар."""
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
        rr = parse_rr(raw)
        m = calc_metrics(rr) if rr else None
        s = calc_stress(rr) if rr else None
        duration = sum(rr) / 1000.0 if rr else 0.0

        rec = ECGRecord(
            athlete_id=aid,
            recorded_at=recorded_at,
            duration_seconds=duration,
            profile="import",
            mean_hr=m["mean_hr"] if m else None,
            rmssd=m["rmssd"] if m else None,
            sdnn=m["sdnn"] if m else None,
            status=m["status"] if m else "ok",
            stress_si=s["si"] if s else None,
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
    """Диалог выбора файлов и пакетный импорт. Возвращает id изменённого атлета."""
    paths = filedialog.askopenfilenames(
        title="Выберите файлы записей ЭКГ (Ctrl/Shift — несколько)",
        filetypes=[("Polar H10", "*.teamloggerh10"), ("Все файлы", "*.*")])
    if not paths:
        return None
    paths = list(paths)
    changed_aid = None

    if len(paths) == 1:
        _, changed_aid = _import_one(db_path, paths[0], athletes,
                                      selected_athlete, status_cb, interactive=True)
        return changed_aid

    stats = {"added": 0, "dup": 0, "skip": 0, "err": 0}
    for p in paths:
        s, aid = _import_one(db_path, p, athletes,
                             selected_athlete, None, interactive=False)
        stats[s] += 1
        if aid:
            changed_aid = aid
        total = stats["added"] + stats["dup"] + stats["skip"] + stats["err"]
        if total % 10 == 0 or total == len(paths):
            status_cb(f"Импорт... {total}/{len(paths)}")

    status_cb(f"Импорт: {stats['added']} доб., {stats['dup']} дубл., "
              f"{stats['skip']} проп., {stats['err']} ош.")
    return changed_aid