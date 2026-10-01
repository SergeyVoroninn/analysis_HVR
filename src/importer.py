"""
importer.py — мгновенный импорт записей в БД и безопасный фоновый расчёт биометрии.
"""
import uuid
import datetime
import os
import threading
from tkinter import messagebox, filedialog

from database import get_db_path
from app_logging import get_logger
from models import get_session, Athlete, ECGRecord, ECGRaw, Device
from analysis import parse_rr, calc_metrics, calc_stress, filter_rr, compute_psd, cfg as analysis_cfg

log = get_logger("importer")

# ИМПОРТ ФУНКЦИЙ И КОНФИГУРАЦИИ БИОМЕТРИИ
from ecg_biometrics import (
    check_ownership_with_saved_template,
    rank_athletes_for_raw,
    auto_update_template_if_needed,
    cfg,
    _are_relatives_by_name
)

# ИМПОРТ КОНСТАНТ БИЗНЕС-ЛОГИКИ (Устранение хардкода порогов)
from app_constants import (
    IMPORT_RELATIVE_PROB_THRESHOLD,
    IMPORT_UNKNOWN_PROB_THRESHOLD,
    IMPORT_PROGRESS_STEP,
    ECG_FILE_EXTENSION
)

# Диалог выбора атлета при биометрическом несовпадении — единое окно сходства.
from dialogs import SimilarityDialog

# ==============================================================================
# ЛОГИКА ИМПОРТА
# ==============================================================================
def _parse_header(raw):
    dt_str, polar = None, None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("datetime="):
            dt_str = line.split("=", 1)[1]
        elif line.startswith("polar_id="):
            polar = line.split("=", 1)[1]
    return dt_str, polar


def _show_import_result(parent_window, status, path):
    filename = os.path.basename(path)
    if status == "dup":
        messagebox.showinfo("Дубликат", f"⚠️ Запись с такой же датой уже существует.\n\nФайл: {filename}", parent=parent_window)
    elif status == "skip":
        messagebox.showwarning("Пропущено", f"⚠️ Не удалось определить атлета.\n\nФайл: {filename}", parent=parent_window)
    elif status == "cancelled":
        messagebox.showinfo("Отменено", f"ℹ️ Импорт отменён.\n\nФайл: {filename}", parent=parent_window)
    elif status == "err":
        messagebox.showerror("Ошибка", f"❌ Не удалось импортировать.\n\nФайл: {filename}", parent=parent_window)


def _import_one(db_path, path, athletes, selected_athlete, status_cb, interactive=True, parent_window=None):
    """
    Выполняет чтение, биометрическую проверку и сохранение в БД.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        log.exception("Не удалось прочитать файл: %s", path)
        if interactive:
            messagebox.showerror("Ошибка чтения", f"Не удалось прочитать файл:\n\n{e}", parent=parent_window)
        return "err", None

    dt_str, polar = _parse_header(raw)
    try:
        dt = datetime.datetime.strptime(dt_str, "%Y.%m.%d %H:%M:%S")
    except Exception:
        dt = datetime.datetime.now().replace(microsecond=0)
    recorded_at = dt.isoformat(sep=" ")

    session = get_session(db_path)
    try:
        existing = session.query(ECGRecord).filter(ECGRecord.recorded_at == recorded_at).first()
        if existing:
            return "dup", None

        athlete = next((a for a in athletes if a[5] == polar), None)
        if athlete is None:
            if not selected_athlete:
                return "skip", None
            athlete = selected_athlete

        aid = athlete[0]
        current_athlete_name = f"{athlete[1]} {athlete[2]}"
        
        # ==========================================================================
        # БИОМЕТРИЧЕСКАЯ ПРОВЕРКА
        # Считается всегда (нужен % схожести для сохранения в БД), а диалоги
        # и подтверждения показываются только в интерактивном режиме.
        # ==========================================================================
        status, distance, prob = check_ownership_with_saved_template(db_path, aid, path)
        bio_prob = prob  # вероятность для итогового атлета (обновляется при перенаправлении)

        if status == "NO_TEMPLATE":
            log.info("Импорт %s: у атлета %s НЕТ шаблона -> сходство не считается, кандидаты не предлагаются",
                     os.path.basename(path), aid)
        elif status == "BAD_SIGNAL":
            log.warning("Импорт %s: плохой сигнал (нет R-зубцов) -> сходство не считается", os.path.basename(path))
        else:
            log.info("Импорт %s: биометрия status=%s distance=%.3f prob=%.3f (атлет %s)",
                     os.path.basename(path), status, distance, prob, aid)

        if interactive and parent_window:
            if status == "NO_TEMPLATE":
                if not messagebox.askyesno("Биометрия", 
                    "Для этого атлета еще нет шаблона. Он будет создан автоматически в фоне.\n\nПродолжить?", 
                    parent=parent_window, icon='info'):
                    return "cancelled", None
                    
            elif status in ("SUSPICIOUS", "LOW_CONFIDENCE"):
                candidates = rank_athletes_for_raw(db_path, raw, current_athlete_id=aid) if raw else []
                best = candidates[0] if candidates else None
                best_athlete = best['athlete'] if best else None
                best_prob = best['probability'] if best else 0.0

                relative_candidates = [m for m in candidates
                                       if _are_relatives_by_name(db_path, aid, m['athlete'].id)]
                best_relative = (max(relative_candidates, key=lambda m: m['probability'])
                                 if relative_candidates else None)
                best_relative_prob = best_relative['probability'] if best_relative else 0.0

                should_show_dialog = False
                if best_relative and best_relative_prob >= IMPORT_RELATIVE_PROB_THRESHOLD:
                    should_show_dialog = True
                    best_athlete = best_relative['athlete']
                    best_prob = best_relative_prob
                elif best_athlete and best_prob >= IMPORT_UNKNOWN_PROB_THRESHOLD:
                    should_show_dialog = True

                if should_show_dialog:
                    # Единое окно биометрического сходства: список всех атлетов
                    # по убыванию совпадения; пользователь выбирает владельца записи.
                    dlg = SimilarityDialog(
                        parent_window, db_path, raw,
                        candidates=candidates,
                        current_athlete_id=aid,
                        title="Биометрическое совпадение",
                        prompt="Запись слабо совпадает с текущим атлетом. "
                               "Укажите, кому принадлежит запись:")
                    res = dlg.modal_loop()
                    if res is None:
                        return "cancelled", None
                    aid = res["athlete_id"]
                    bio_prob = res["probability"]

                else:
                    msg = (f"⚠️ Биометрическое сходство низкое!\n\n"
                           f"Вероятность совпадения с текущим атлетом: {prob*100:.1f}%\n"
                           f"Расстояние до шаблона: {distance:.3f}\n\n"
                           f"В базе не найдено подходящих совпадений (все ниже {IMPORT_UNKNOWN_PROB_THRESHOLD*100:.0f}%).\n"
                           f"Скорее всего, это НОВЫЙ человек.\n\n"
                           f"Продолжить импорт текущему атлету?")
                    if not messagebox.askyesno("Новый человек?", msg, parent=parent_window, icon='warning'):
                        return "cancelled", None
            
            # ⚡ ПРОВЕРКА ПОГРАНИЧНОГО MATCH (используем конфиг, без хардкода)
            elif status == "MATCH" and distance > cfg.MATCH_WARNING_THRESHOLD:
                msg = (f"ℹ️ Запись импортирована, но сходство пограничное.\n\n"
                       f"Атлет: {current_athlete_name}\n"
                       f"Расстояние до шаблона: {distance:.3f}\n"
                       f"Вероятность совпадения: {prob*100:.1f}%\n\n"
                       f"Рекомендуется проверить запись вручную.")
                messagebox.showinfo("Пограничное совпадение", msg, parent=parent_window)

        # ==========================================================================
        # МГНОВЕННОЕ СОХРАНЕНИЕ В БД
        # (Вынесено за пределы if interactive, чтобы работало и при пакетном импорте)
        # ==========================================================================
        rr = parse_rr(raw)
        seq = filter_rr(rr) if rr else [] 
        m = calc_metrics(seq) if seq else None
        s = calc_stress(seq) if seq else None
        duration = sum(rr) / 1000.0 if rr else 0.0

        spectral_tp = None
        if seq and len(seq) >= analysis_cfg.MIN_RR_FOR_METRICS:
            try:
                _, _, bands = compute_psd(seq)
                spectral_tp = bands.get("tp")
            except Exception:
                pass

        # Прибор, которым сделана запись (если polar_id есть в шапке файла)
        device_id = None
        if polar:
            dev = session.query(Device).filter(Device.serial_number == polar).first()
            if dev is None:
                dev = Device(serial_number=polar)  # model по умолчанию "Polar H10"
                session.add(dev)
                session.flush()
            device_id = dev.id

        # % биологической схожести с эталонным шаблоном атлета
        # (None, если корректного сравнения не было: нет шаблона, ошибка, плохой сигнал)
        bio_pct = None
        bio_note = None
        if status == "NO_TEMPLATE":
            bio_note = "нет шаблона у атлета"
        elif status == "BAD_SIGNAL":
            from ecg_biometrics import bio_failure_reason
            bio_note = bio_failure_reason(raw)
            log.warning("Импорт %s: %s", os.path.basename(path), bio_note)
        elif status == "ERROR":
            bio_note = "ошибка обработки сигнала"
        elif bio_prob is not None:
            bio_pct = round(bio_prob * 100, 2)

        rec = ECGRecord(
            athlete_id=aid, recorded_at=recorded_at, duration_seconds=duration,
            mean_hr=m["mean_hr"] if m else None, rmssd=m["rmssd"] if m else None,
            status=m["status"] if m else "ok",
            stress_si=s["si"] if s else None, tp=spectral_tp,
            device_id=device_id, bio_similarity_pct=bio_pct, bio_note=bio_note,
        )
        session.add(rec)
        session.flush()
        rec.raw = ECGRaw(record_id=rec.id, raw_data=raw)
        session.commit()
        
        return "added", aid

    except Exception as e:
        session.rollback()
        log.exception("Ошибка при импорте %s", path)
        if interactive:
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить:\n\n{e}", parent=parent_window)
        return "err", None
    finally:
        session.close()


def _bg_update_template(db_path, aid):
    """Обёртка для безопасного фонового обновления."""
    try:
        auto_update_template_if_needed(db_path, aid)
    except Exception:
        pass


def import_ecg(parent, db_path, athletes, selected_athlete, status_cb):
    paths = filedialog.askopenfilenames(
        title="Выберите файлы записей ЭКГ",
        filetypes=[("Polar H10", f"*{ECG_FILE_EXTENSION}"), ("Все файлы", "*.*")])
    if not paths:
        return None
    paths = list(paths)
    changed_aid = None
    updated_athletes = set()

    if len(paths) == 1:
        status, changed_aid = _import_one(db_path, paths[0], athletes, selected_athlete, status_cb, interactive=True, parent_window=parent)
        if status != "added":
            _show_import_result(parent, status, paths[0])
        elif changed_aid:
            updated_athletes.add(changed_aid)
        return changed_aid

    # Пакетный импорт
    stats = {"added": 0, "dup": 0, "skip": 0, "err": 0, "cancelled": 0}
    for p in paths:
        s, aid = _import_one(db_path, p, athletes, selected_athlete, None, interactive=False, parent_window=None)
        stats[s] = stats.get(s, 0) + 1
        if s == "added" and aid:
            changed_aid = aid
            updated_athletes.add(aid)
            
        total = sum(stats.values())
        if total % IMPORT_PROGRESS_STEP == 0 or total == len(paths):
            status_cb(f"Импорт... {total}/{len(paths)}")

    # Фоновый расчёт шаблонов
    for aid in updated_athletes:
        threading.Thread(target=_bg_update_template, args=(db_path, aid), daemon=True).start()

    # Финальное сообщение
    msg_parts = []
    if stats['added'] > 0: msg_parts.append(f"✅ Добавлено: {stats['added']}")
    if stats['dup'] > 0: msg_parts.append(f"⚠️ Дубликатов: {stats['dup']}")
    if stats['skip'] > 0: msg_parts.append(f"⏭️ Пропущено: {stats['skip']}")
    if stats['err'] > 0: msg_parts.append(f"❌ Ошибок: {stats['err']}")
    if stats['cancelled'] > 0: msg_parts.append(f"🚫 Отменено: {stats['cancelled']}")
    
    final_msg = "\n".join(msg_parts) if msg_parts else "Ничего не импортировано."
    status_cb(final_msg.replace("\n", " | "))
    
    if stats['dup'] > 0 or stats['err'] > 0 or stats['cancelled'] > 0:
        messagebox.showinfo("Итоги импорта", f"Импорт завершён.\n\n{final_msg}", parent=parent)
    
    return changed_aid