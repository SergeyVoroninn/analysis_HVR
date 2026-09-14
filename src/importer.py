"""
importer.py — импорт записей Polar H10 в БД с умной биометрической верификацией.
"""
import uuid
import datetime
import os
import tkinter as tk
from tkinter import messagebox, filedialog

from database import get_db_path
from models import get_session, Athlete, ECGRecord, ECGRaw
from analysis import parse_rr, calc_metrics, calc_stress, filter_rr, compute_psd

# ИМПОРТ ФУНКЦИЙ БИОМЕТРИИ
from ecg_biometrics import (
    check_ownership_with_saved_template, 
    find_best_match
)


# ==============================================================================
# ДИАЛОГ ВЫБОРА АТЛЕТА ПРИ БИОМЕТРИЧЕСКОМ НЕСОВПАДЕНИИ
# ==============================================================================
class BiometricChoiceDialog(tk.Toplevel):
    def __init__(self, parent, current_name, current_prob, best_name, best_prob):
        super().__init__(parent)
        self.title("🔍 Биометрическая верификация")
        self.geometry("550x480")  #  УВЕЛИЧЕНО с 420 до 480
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.configure(bg="#2b2b2b")

        # Заголовок
        tk.Label(self, text="Обнаружено расхождение биометрических данных", 
                 font=("Segoe UI", 12, "bold"), bg="#2b2b2b", fg="#ffffff").pack(pady=10)
        
        # Пояснение
        tk.Label(self, text="Если ни один из вариантов не подходит, выберите отмену импорта.", 
                 font=("Segoe UI", 9), bg="#2b2b2b", fg="#ffb74d").pack(pady=(0, 10))

        # Текущий атлет
        cur_frame = tk.Frame(self, bg="#1e3a5f", padx=15, pady=10)
        cur_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(cur_frame, text=f"👤 Текущий выбор:", font=("Segoe UI", 10), bg="#1e3a5f", fg="#90caf9").pack(anchor="w")
        tk.Label(cur_frame, text=current_name, font=("Segoe UI", 11, "bold"), bg="#1e3a5f", fg="#ffffff").pack(anchor="w")
        tk.Label(cur_frame, text=f"Совпадение с шаблоном: {current_prob:.1f}%", font=("Segoe UI", 10), bg="#1e3a5f", fg="#ffb74d").pack(anchor="w")

        # Лучший кандидат
        best_frame = tk.Frame(self, bg="#1b5e20", padx=15, pady=10)
        best_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(best_frame, text=f"🎯 Найдено лучшее совпадение в базе:", font=("Segoe UI", 10), bg="#1b5e20", fg="#a5d6a7").pack(anchor="w")
        tk.Label(best_frame, text=best_name, font=("Segoe UI", 11, "bold"), bg="#1b5e20", fg="#ffffff").pack(anchor="w")
        tk.Label(best_frame, text=f"Совпадение с шаблоном: {best_prob:.1f}%", font=("Segoe UI", 10, "bold"), bg="#1b5e20", fg="#ffffff").pack(anchor="w")

        # Кнопки
        btn_frame = tk.Frame(self, bg="#2b2b2b")
        btn_frame.pack(fill="x", padx=20, pady=15)  # ⚡ УМЕНЬШЕНО с 20 до 15

        tk.Button(btn_frame, text=f"✅ Привязать к: {best_name.split()[0]}", 
                  command=lambda: self._close("best"), bg="#4caf50", fg="white", 
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)  # ⚡ УМЕНЬШЕНО

        tk.Button(btn_frame, text=f"✓ Оставить у текущего: {current_name.split()[0]}", 
                  command=lambda: self._close("current"), bg="#2196f3", fg="white", 
                  font=("Segoe UI", 10), relief="flat", cursor="hand2").pack(fill="x", pady=3)  # ⚡ УМЕНЬШЕНО

        # ЯВНАЯ КНОПКА ОТМЕНЫ
        tk.Button(btn_frame, text="❌ Ни один не подходит (Отменить импорт)", 
                  command=lambda: self._close("cancel"), bg="#f44336", fg="white", 
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2").pack(fill="x", pady=3)  # ⚡ УМЕНЬШЕНО

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
    """
    Показывает понятное сообщение пользователю при одиночном импорте.
    """
    filename = os.path.basename(path)
    
    if status == "dup":
        messagebox.showinfo(
            "Дубликат",
            f"️ Запись с такой же датой и временем уже существует в базе.\n\n"
            f"Файл: {filename}\n\n"
            f"Импорт пропущен.",
            parent=parent_window
        )
    elif status == "skip":
        messagebox.showwarning(
            "Пропущено",
            f"⚠️ Не удалось определить атлета для этой записи.\n\n"
            f"Файл: {filename}\n\n"
            f"Возможно, polar_id не совпадает ни с одним спортсменом в базе.\n"
            f"Выберите атлета вручную и повторите импорт.",
            parent=parent_window
        )
    elif status == "cancelled":
        messagebox.showinfo(
            "Импорт отменён",
            f"️ Импорт отменён пользователем.\n\n"
            f"Файл: {filename}",
            parent=parent_window
        )
    elif status == "err":
        messagebox.showerror(
            "Ошибка импорта",
            f"❌ Не удалось импортировать запись.\n\n"
            f"Файл: {filename}\n\n"
            f"Проверьте целостность файла и повторите попытку.",
            parent=parent_window
        )


def _import_one(db_path, path, athletes, selected_athlete, status_cb, interactive=True, parent_window=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        if interactive:
            messagebox.showerror("Ошибка чтения файла", f"Не удалось прочитать файл:\n\n{e}", parent=parent_window)
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
        current_athlete_name = f"{athlete[1]} {athlete[2]}"
        
        # ⚡ УМНАЯ БИОМЕТРИЧЕСКАЯ ПРОВЕРКА
        if interactive and parent_window:
            status, distance, prob = check_ownership_with_saved_template(db_path, aid, path)
            
            if status == "NO_TEMPLATE":
                if not messagebox.askyesno("Биометрия", 
                    "Для этого атлета еще не создан биометрический шаблон.\n"
                    "Рекомендуется создать его в списке записей атлета.\n\n"
                    "Продолжить импорт?", parent=parent_window, icon='info'):
                    return "cancelled", None
                    
            elif status in ("SUSPICIOUS", "LOW_CONFIDENCE"):
                # Ищем лучшее совпадение по всей базе (исключая текущего)
                best_athlete, best_dist, best_prob, all_matches = find_best_match(db_path, path, exclude_athlete_id=aid)
                
                # Если нашли кого-то с вероятностью выше, чем у текущего, показываем диалог выбора
                if best_athlete and best_prob > prob:
                    best_athlete_name = f"{best_athlete.last_name} {best_athlete.first_name}"
                    
                    dialog = BiometricChoiceDialog(
                        parent_window, 
                        current_athlete_name, prob * 100, 
                        best_athlete_name, best_prob * 100
                    )
                    parent_window.wait_window(dialog)
                    
                    if dialog.result == "best":
                        aid = best_athlete.id  # Переключаем ID атлета на лучшего кандидата
                    elif dialog.result == "cancel":
                        return "cancelled", None  # ⚡ ЯВНАЯ ОТМЕНА
                    # Если "current", просто продолжаем с текущим aid
                
                else:
                    # Лучшего совпадения нет или оно хуже текущего. Показываем старое предупреждение.
                    if status == "SUSPICIOUS":
                        msg = (f"🚨 ВНИМАНИЕ: Низкое биометрическое сходство!\n\n"
                               f"Индекс различия: {distance:.3f}\n"
                               f"Вероятность совпадения: {prob*100:.1f}%\n\n"
                               f"Эта запись, скорее всего, принадлежит ДРУГОМУ человеку.\n"
                               f"Вы уверены, что хотите импортировать её этому атлету?")
                        if not messagebox.askyesno("Проверка принадлежности", msg, parent=parent_window, icon='warning'):
                            return "cancelled", None  # ⚡ ЯВНАЯ ОТМЕНА

        # --- Если дошли сюда, импортируем ---
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
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить запись:\n\n{e}", parent=parent_window)
        return "err", None
    finally:
        session.close()

    if interactive and status_cb:
        status_cb(f"Запись добавлена: {dt:%d.%m.%Y %H:%M}")
    return "added", aid


def import_ecg(parent, db_path, athletes, selected_athlete, status_cb):
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
        # ⚡ НОВОЕ: Показываем понятное сообщение при любом не-успешном исходе
        if status != "added":
            _show_import_result(parent, status, paths[0])
        return changed_aid

    # Пакетный импорт
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

    # ⚡ НОВОЕ: Финальное сообщение с полной статистикой
    msg_parts = []
    if stats['added'] > 0:
        msg_parts.append(f"✅ Добавлено: {stats['added']}")
    if stats['dup'] > 0:
        msg_parts.append(f"⚠️ Дубликатов: {stats['dup']}")
    if stats['skip'] > 0:
        msg_parts.append(f"⏭️ Пропущено: {stats['skip']}")
    if stats['err'] > 0:
        msg_parts.append(f"❌ Ошибок: {stats['err']}")
    if stats['cancelled'] > 0:
        msg_parts.append(f"🚫 Отменено: {stats['cancelled']}")
    
    final_msg = "\n".join(msg_parts) if msg_parts else "Ничего не импортировано."
    
    # Показываем итог в статус-баре
    status_cb(final_msg.replace("\n", " | "))
    
    # Если были проблемы (дубликаты, ошибки, отмены) — показываем подробное окно
    if stats['dup'] > 0 or stats['err'] > 0 or stats['cancelled'] > 0:
        messagebox.showinfo(
            "Итоги импорта",
            f"Импорт завершён.\n\n{final_msg}",
            parent=parent
        )
    
    return changed_aid