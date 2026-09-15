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
from analysis import parse_rr, calc_metrics, calc_stress, filter_rr, compute_psd

# ИМПОРТ ФУНКЦИЙ БИОМЕТРИИ
from ecg_biometrics import (
    check_ownership_with_saved_template, 
    find_best_match,
    auto_update_template_if_needed
)


# ==============================================================================
# ДИАЛОГ ВЫБОРА АТЛЕТА ПРИ БИОМЕТРИЧЕСКОМ НЕСОВПАДЕНИИ
# ==============================================================================
class BiometricChoiceDialog(tk.Toplevel):
    def __init__(self, parent, current_name, current_prob, best_name, best_prob, 
                 is_relative=False, best_records=0): # ⚡ Добавлен best_records
        super().__init__(parent)
        self.title("🔍 Биометрическая верификация")
        self.geometry("550x500") # Чуть выше для нового текста
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.configure(bg="#2b2b2b")

        tk.Label(self, text="Обнаружено расхождение биометрических данных", 
                 font=("Segoe UI", 12, "bold"), bg="#2b2b2b", fg="#ffffff").pack(pady=10)
        
        tk.Label(self, text="Если ни один из вариантов не подходит, выберите отмену импорта.", 
                 font=("Segoe UI", 9), bg="#2b2b2b", fg="#ffb74d").pack(pady=(0, 10))

        # Текущий атлет
        cur_frame = tk.Frame(self, bg="#1e3a5f", padx=15, pady=10)
        cur_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(cur_frame, text=f"👤 Текущий выбор:", font=("Segoe UI", 10), bg="#1e3a5f", fg="#90caf9").pack(anchor="w")
        tk.Label(cur_frame, text=current_name, font=("Segoe UI", 11, "bold"), bg="#1e3a5f", fg="#ffffff").pack(anchor="w")
        tk.Label(cur_frame, text=f"Совпадение: {current_prob:.1f}%", font=("Segoe UI", 10), bg="#1e3a5f", fg="#ffb74d").pack(anchor="w")

        # Лучший кандидат
        best_frame = tk.Frame(self, bg="#1b5e20", padx=15, pady=10)
        best_frame.pack(fill="x", padx=20, pady=5)
        
        relative_marker = " 👥 (возможно, родственник)" if is_relative else ""
        tk.Label(best_frame, text=f"🎯 Найдено лучшее совпадение{relative_marker}:", 
                 font=("Segoe UI", 10), bg="#1b5e20", fg="#a5d6a7").pack(anchor="w")
        tk.Label(best_frame, text=best_name, font=("Segoe UI", 11, "bold"), bg="#1b5e20", fg="#ffffff").pack(anchor="w")
        
        # ⚡ НОВОЕ: Показываем надежность шаблона
        reliability_text = ""
        if best_records < 10:
            reliability_text = f" ⚠️ (Шаблон ненадежен: всего {best_records} записей)"
            prob_color = "#ffab91" # Оранжевый для предупреждения
        elif best_records < 20:
            reliability_text = f" (Шаблон формируется: {best_records} записей)"
            prob_color = "#ffffff"
        else:
            reliability_text = f" (Надежный шаблон: {best_records} записей)"
            prob_color = "#ffffff"

        tk.Label(best_frame, text=f"Совпадение: {best_prob:.1f}%{reliability_text}", 
                 font=("Segoe UI", 10, "bold"), bg="#1b5e20", fg=prob_color).pack(anchor="w")

        # Кнопки (без изменений)
        btn_frame = tk.Frame(self, bg="#2b2b2b")
        btn_frame.pack(fill="x", padx=20, pady=15)

        tk.Button(btn_frame, text=f"✅ Привязать к: {best_name.split()[0]}", 
                  command=lambda: self._close("best"), bg="#4caf50", fg="white", 
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text=f"✓ Оставить у текущего: {current_name.split()[0]}", 
                  command=lambda: self._close("current"), bg="#2196f3", fg="white", 
                  font=("Segoe UI", 10), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        tk.Button(btn_frame, text="❌ Ни один не подходит (Отменить импорт)", 
                  command=lambda: self._close("cancel"), bg="#f44336", fg="white", 
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)

        self.bind("<Escape>", lambda e: self._close("cancel"))
        self.focus_force()

    def _close(self, result):
        self.result = result
        self.destroy()

def _are_relatives_by_name(db_path, athlete_id_1, athlete_id_2):
    """Проверяет, являются ли атлеты родственниками по фамилии."""
    if not athlete_id_1 or not athlete_id_2:
        return False
    
    session = get_session(db_path)
    try:
        a1 = session.query(Athlete).filter_by(id=athlete_id_1).first()
        a2 = session.query(Athlete).filter_by(id=athlete_id_2).first()
        
        if not a1 or not a2:
            return False
        
        # Сравниваем фамилии (без учета регистра)
        return a1.last_name.lower() == a2.last_name.lower()
    finally:
        session.close()

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
    Выполняет ТОЛЬКО чтение и сохранение в БД. Максимально быстро.
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
        
        # ⚡ БИОМЕТРИЧЕСКАЯ ПРОВЕРКА (только для интерактивного режима)
        if interactive and parent_window:
            status, distance, prob = check_ownership_with_saved_template(db_path, aid, path)
            
            if status == "NO_TEMPLATE":
                if not messagebox.askyesno("Биометрия", 
                    "Для этого атлета еще нет шаблона. Он будет создан автоматически в фоне.\n\nПродолжить?", 
                    parent=parent_window, icon='info'):
                    return "cancelled", None
                    
            elif status in ("SUSPICIOUS", "LOW_CONFIDENCE"):
                # Ищем лучшее совпадение по всей базе (исключая текущего)
                best_athlete, best_dist, best_prob, all_matches = find_best_match(db_path, path, exclude_athlete_id=aid)
                
                # ⚡ НОВОЕ: Абсолютный порог для предотвращения ложных совпадений
                ABSOLUTE_THRESHOLD = 0.20  # 20% - минимальная вероятность для предложения
                
                # Проверяем родственников
                has_relatives = False
                relative_candidates = []
                for m in all_matches:
                    if _are_relatives_by_name(db_path, aid, m['athlete'].id):
                        has_relatives = True
                        relative_candidates.append(m)
                
                # ⚡ НОВОЕ: Проверяем, есть ли родственники с высокой вероятностью
                best_relative = None
                best_relative_prob = 0
                for m in relative_candidates:
                    if m['probability'] > best_relative_prob:
                        best_relative = m
                        best_relative_prob = m['probability']
                
                # Логика принятия решения
                should_show_dialog = False
                
                if best_relative and best_relative_prob >= 0.25:  # Для родственников порог чуть выше (25%)
                    # Нашли родственника с достаточной вероятностью
                    should_show_dialog = True
                    best_athlete = best_relative['athlete']
                    best_prob = best_relative_prob
                elif best_athlete and best_prob >= ABSOLUTE_THRESHOLD:
                    # Нашли неродственного кандидата с достаточной вероятностью
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
                    # ⚡ НОВОЕ: Все совпадения ниже порога - это новый человек
                    msg = (f"⚠️ Биометрическое сходство низкое!\n\n"
                           f"Вероятность совпадения с текущим атлетом: {prob*100:.1f}%\n\n"
                           f"В базе не найдено подходящих совпадений (все ниже 20%).\n"
                           f"Скорее всего, это НОВЫЙ человек.\n\n"
                           f"Продолжить импорт текущему атлету?")
                    if not messagebox.askyesno("Новый человек?", msg, parent=parent_window, icon='warning'):
                        return "cancelled", None

        # --- МГНОВЕННОЕ СОХРАНЕНИЕ В БД ---
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
        pass # Тихо игнорируем, чтобы не засорять консоль


def import_ecg(parent, db_path, athletes, selected_athlete, status_cb):
    paths = filedialog.askopenfilenames(
        title="Выберите файлы записей ЭКГ",
        filetypes=[("Polar H10", "*.teamloggerh10"), ("Все файлы", "*.*")])
    if not paths:
        return None
    paths = list(paths)
    changed_aid = None

    # Множество для хранения уникальных ID атлетов, которым добавились записи
    updated_athletes = set()

    if len(paths) == 1:
        status, changed_aid = _import_one(db_path, paths[0], athletes, selected_athlete, status_cb, interactive=True, parent_window=parent)
        if status != "added":
            _show_import_result(parent, status, paths[0])
        elif changed_aid:
            updated_athletes.add(changed_aid)
        return changed_aid

    # Пакетный импорт (без диалогов, максимально быстро)
    stats = {"added": 0, "dup": 0, "skip": 0, "err": 0, "cancelled": 0}
    for p in paths:
        s, aid = _import_one(db_path, p, athletes, selected_athlete, None, interactive=False, parent_window=None)
        stats[s] = stats.get(s, 0) + 1
        if s == "added" and aid:
            changed_aid = aid
            updated_athletes.add(aid) # Запоминаем, что у этого атлета появились новые данные
            
        total = sum(stats.values())
        if total % 10 == 0 or total == len(paths):
            status_cb(f"Импорт... {total}/{len(paths)}")

    # ⚡ ГЛАВНОЕ ИЗМЕНЕНИЕ: Запускаем расчёт шаблонов В ФОНЕ, ПОСЛЕ того как всё сохранено в БД
    # И делаем это ровно один раз для каждого уникального атлета
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