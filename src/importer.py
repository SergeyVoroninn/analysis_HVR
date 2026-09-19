"""
importer.py — мгновенный импорт записей в БД и безопасный фоновый расчёт биометрии.
"""
import uuid
import datetime
import os
import threading
import tkinter as tk
from tkinter import messagebox, filedialog

from database import get_db_path
from models import get_session, Athlete, ECGRecord, ECGRaw
from analysis import parse_rr, calc_metrics, calc_stress, filter_rr, compute_psd, cfg as analysis_cfg

# ИМПОРТ ФУНКЦИЙ И КОНФИГУРАЦИИ БИОМЕТРИИ
from ecg_biometrics import (
    check_ownership_with_saved_template, 
    find_best_match,
    auto_update_template_if_needed,
    cfg,
    _are_relatives_by_name
)

# ИМПОРТ ЦВЕТОВОЙ ПАЛИТРЫ (Устранение хардкода цветов)
from theme import (
    COL_BG_DARK, COL_BG_WIDGET, COL_TEXT_LIGHT, COL_TEXT_DIM,
    COL_ONE, COL_WARN, COL_CRIT, COL_ACCENT, COL_SELECTION
)

# ИМПОРТ КОНСТАНТ БИЗНЕС-ЛОГИКИ (Устранение хардкода порогов)
from app_constants import (
    IMPORT_RELATIVE_PROB_THRESHOLD,
    IMPORT_UNKNOWN_PROB_THRESHOLD,
    ECG_FILE_EXTENSION
)

# ==============================================================================
# ДИАЛОГ ВЫБОРА АТЛЕТА ПРИ БИОМЕТРИЧЕСКОМ НЕСОВПАДЕНИИ
# ==============================================================================
class BiometricChoiceDialog(tk.Toplevel):
    def __init__(self, parent, current_name, current_prob, best_name, best_prob, 
                 is_relative=False, best_records=0):
        super().__init__(parent)
        self.title("🔍 Биометрическая верификация")
        self.geometry("550x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.protocol("WM_DELETE_WINDOW", lambda: self._close("cancel"))

        self.configure(bg=COL_BG_DARK)  # <-- ЗАМЕНЕНО

        tk.Label(self, text="Обнаружено расхождение биометрических данных", 
                 font=("Segoe UI", 12, "bold"), bg=COL_BG_DARK, fg=COL_TEXT_LIGHT).pack(pady=10)  # <-- ЗАМЕНЕНО
        
        tk.Label(self, text="Если ни один из вариантов не подходит, выберите отмену импорта.", 
                 font=("Segoe UI", 9), bg=COL_BG_DARK, fg=COL_WARN).pack(pady=(0, 10))  # <-- ЗАМЕНЕНО

        # Текущий атлет (используем COL_ACCENT вместо #1e3a5f)
        cur_frame = tk.Frame(self, bg=COL_ACCENT, padx=15, pady=10)
        cur_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(cur_frame, text=f"👤 Текущий выбор:", font=("Segoe UI", 10), bg=COL_ACCENT, fg=COL_TEXT_LIGHT).pack(anchor="w")
        tk.Label(cur_frame, text=current_name, font=("Segoe UI", 11, "bold"), bg=COL_ACCENT, fg=COL_SELECTION).pack(anchor="w")
        tk.Label(cur_frame, text=f"Совпадение: {current_prob:.1f}%", font=("Segoe UI", 10), bg=COL_ACCENT, fg=COL_WARN).pack(anchor="w")

        # Лучший кандидат (используем COL_ONE вместо #1b5e20)
        best_frame = tk.Frame(self, bg=COL_ONE, padx=15, pady=10)
        best_frame.pack(fill="x", padx=20, pady=5)
        
        relative_marker = " 👥 (возможно, родственник)" if is_relative else ""
        tk.Label(best_frame, text=f"🎯 Найдено лучшее совпадение{relative_marker}:", 
                 font=("Segoe UI", 10), bg=COL_ONE, fg=COL_TEXT_LIGHT).pack(anchor="w")
        tk.Label(best_frame, text=best_name, font=("Segoe UI", 11, "bold"), bg=COL_ONE, fg=COL_SELECTION).pack(anchor="w")
        
        reliability_text = ""
        # Используем пороги из централизованной конфигурации биометрии
        if best_records < cfg.RELIABILITY_LOW_THRESH:
            reliability_text = f" ⚠️ (Шаблон ненадежен: всего {best_records} записей)"
            prob_color = COL_CRIT
        elif best_records < cfg.RELIABILITY_HIGH_THRESH:
            reliability_text = f" (Шаблон формируется: {best_records} записей)"
            prob_color = COL_SELECTION
        else:
            reliability_text = f" (Надежный шаблон: {best_records} записей)"
            prob_color = COL_SELECTION

        tk.Label(best_frame, text=f"Совпадение: {best_prob:.1f}%{reliability_text}", 
                 font=("Segoe UI", 10, "bold"), bg=COL_ONE, fg=prob_color).pack(anchor="w")

        # Кнопки
        btn_frame = tk.Frame(self, bg=COL_BG_DARK)
        btn_frame.pack(fill="x", padx=20, pady=15)

        tk.Button(btn_frame, text=f"✅ Привязать к: {best_name.split()[0]}", 
                  command=lambda: self._close("best"), bg=COL_ONE, fg=COL_SELECTION,  # <-- ЗАМЕНЕНО (#4caf50)
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text=f"✓ Оставить у текущего: {current_name.split()[0]}", 
                  command=lambda: self._close("current"), bg=COL_ACCENT, fg=COL_SELECTION,  # <-- ЗАМЕНЕНО (#2196f3)
                  font=("Segoe UI", 10), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text="❌ Ни один не подходит (Отменить импорт)", 
                  command=lambda: self._close("cancel"), bg=COL_CRIT, fg=COL_SELECTION,  # <-- ЗАМЕНЕНО (#f44336)
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        self.bind("<Escape>", lambda e: self._close("cancel"))
        self.focus_force()

    def _close(self, result):
        self.result = result
        self.destroy()

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
        # БИОМЕТРИЧЕСКАЯ ПРОВЕРКА (только для интерактивного режима)
        # ==========================================================================
        if interactive and parent_window:
            status, distance, prob = check_ownership_with_saved_template(db_path, aid, path)
            
            if status == "NO_TEMPLATE":
                if not messagebox.askyesno("Биометрия", 
                    "Для этого атлета еще нет шаблона. Он будет создан автоматически в фоне.\n\nПродолжить?", 
                    parent=parent_window, icon='info'):
                    return "cancelled", None
                    
            elif status in ("SUSPICIOUS", "LOW_CONFIDENCE"):
                best_athlete, best_dist, best_prob, all_matches = find_best_match(db_path, path, exclude_athlete_id=aid)
                
                has_relatives = False
                relative_candidates = []
                for m in all_matches:
                    if _are_relatives_by_name(db_path, aid, m['athlete'].id):
                        has_relatives = True
                        relative_candidates.append(m)
                
                best_relative = None
                best_relative_prob = 0
                for m in relative_candidates:
                    if m['probability'] > best_relative_prob:
                        best_relative = m
                        best_relative_prob = m['probability']
                
                should_show_dialog = False
                
                if best_relative and best_relative_prob >= IMPORT_RELATIVE_PROB_THRESHOLD:
                    should_show_dialog = True
                    best_athlete = best_relative['athlete']
                    best_prob = best_relative_prob
                elif best_athlete and best_prob >= IMPORT_UNKNOWN_PROB_THRESHOLD:
                    should_show_dialog = True
                
                if should_show_dialog:
                    best_athlete_name = f"{best_athlete.last_name} {best_athlete.first_name}"
                    is_best_relative = best_relative is not None
                    best_records = next((m['records_used'] for m in all_matches if m['athlete'].id == best_athlete.id), 0)
                    
                    dialog = BiometricChoiceDialog(
                        parent_window, 
                        current_athlete_name, prob * 100, 
                        best_athlete_name, best_prob * 100,
                        is_relative=is_best_relative,
                        best_records=best_records
                    )
                    
                    parent_window.wait_window(dialog)
                    
                    if dialog.result == "best":
                        aid = best_athlete.id
                    elif dialog.result == "cancel":
                        return "cancelled", None
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

        rec = ECGRecord(
            athlete_id=aid, recorded_at=recorded_at, duration_seconds=duration,
            mean_hr=m["mean_hr"] if m else None, rmssd=m["rmssd"] if m else None,
            sdnn=m["sdnn"] if m else None, status=m["status"] if m else "ok",
            stress_si=s["si"] if s else None, tp=spectral_tp,
        )
        session.add(rec)
        session.flush()
        rec.raw = ECGRaw(record_id=rec.id, raw_data=raw)
        session.commit()
        
        return "added", aid

    except Exception as e:
        session.rollback()
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
        if total % 10 == 0 or total == len(paths):
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