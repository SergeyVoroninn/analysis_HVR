"""Единый журнал записей ЭКГ."""
import datetime
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog

from models import get_session, ECGRecord, ECGRaw, Athlete, Device

from theme import (COL_BG_DARK, COL_WARN, COL_CRIT, COL_SELECTION,
                   COL_TEXT_LIGHT, COL_TEXT_DIM)

from app_constants import (ECG_FILE_EXTENSION, ECGLIST_DEFAULT_LIMIT,
                           BIO_SIMILARITY_WARN_PCT, BIO_SIMILARITY_CRIT_PCT)

from .base import BaseDialog, CANCEL, DANGER


class ECGJournal(BaseDialog):
    """Единый журнал записей ЭКГ (используется и из heatmap, и из главной формы).

    Режимы выборки:
      * интервал: date_from/date_to по recorded_at (из недельного heatmap),
        сортировка по умолчанию — время снятия (recorded_at ASC);
      * последние: limit по времени импорта (updated_at DESC), конкретный атлет
        или все (из главной формы).

    Сортировка — кликом по заголовку любой колонки, а также кнопками
    «По времени снятия» / «По времени импорта». Записи с низкой биологической
    схожестью с шаблоном подсвечиваются цветом (< WARN — жёлтым, < CRIT — красным).
    """

    DISPLAY_COLS = ("Атлет", "Прибор", "Время", "Импорт", "Сходство",
                    "ЧСС", "RMSSD", "SDNN", "ИС", "TP", "Статус")

    # имя колонки -> (ORM-таблица, атрибут) для order_by
    SORT_ATTR = {
        "Атлет": (Athlete, Athlete.last_name),
        "Прибор": (Device, Device.serial_number),
        "Время": (ECGRecord, ECGRecord.recorded_at),
        "Импорт": (ECGRecord, ECGRecord.updated_at),
        "Сходство": (ECGRecord, ECGRecord.bio_similarity_pct),
        "ЧСС": (ECGRecord, ECGRecord.mean_hr),
        "RMSSD": (ECGRecord, ECGRecord.rmssd),
        "SDNN": (ECGRecord, ECGRecord.sdnn),
        "ИС": (ECGRecord, ECGRecord.stress_si),
        "TP": (ECGRecord, ECGRecord.tp),
        "Статус": (ECGRecord, ECGRecord.status),
    }

    def __init__(self, parent, *, athlete_id=None, date_from=None, date_to=None,
                 limit=None, db_path=None, title="Журнал ЭКГ", on_change=None):
        db = db_path or getattr(parent, "db_path", None)
        super().__init__(parent, title=title, db_path=db,
                         size="1150x520", resizable=(True, True), modal=True)

        self.athlete_id = athlete_id
        self.date_from = date_from
        self.date_to = date_to
        self.limit = limit
        self.on_change = on_change

        # Сортировка по умолчанию: для интервала — по времени снятия (Время, ASC),
        # для "последних" — по времени импорта (Импорт, DESC).
        self._sort_col = "Время" if date_from is not None else "Импорт"
        self._sort_desc = date_from is None

        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(padx=12, pady=8)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.tree = ttk.Treeview(frame, columns=self.DISPLAY_COLS, show="headings",
                                 height=14)
        widths = {"Атлет": 150, "Прибор": 120, "Время": 120, "Импорт": 120,
                  "Сходство": 80, "ЧСС": 70, "RMSSD": 70, "SDNN": 70,
                  "ИС": 70, "TP": 80, "Статус": 80}
        for c in self.DISPLAY_COLS:
            self.tree.heading(c, text=c, command=lambda _c=c: self._sort_by(_c))
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.tag_configure("warn", background=COL_WARN, foreground=COL_BG_DARK)
        self.tree.tag_configure("crit", background=COL_CRIT, foreground=COL_SELECTION)
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btns = self.make_button_bar(self, pady=6)
        self.make_button(btns, "По времени снятия", lambda: self._sort_preset("Время", False), width=110,
                         tooltip="Сортировать по времени снятия записи (по возрастанию)")
        self.make_button(btns, "По времени импорта", lambda: self._sort_preset("Импорт", True), width=130,
                         tooltip="Сортировать по времени импорта (по убыванию)")
        self.btn_export = self.make_button(btns, " Экспорт в файл", self._export, state="disabled",
                                           tooltip="Сохранить сырые данные записи в файл .teamloggerh10")
        self.btn_delete = self.make_button(btns, "🗑 Удалить", self._delete,
                                           kind=DANGER, state="disabled",
                                           tooltip="Удалить выбранную запись ЭКГ")
        self.btn_improve = self.make_button(btns, "🎯 Улучшить сходство",
                                            self._improve_similarity, state="disabled",
                                            tooltip="Подобрать более подходящего атлета для записи")
        self.make_button(btns, "Закрыть", self.close, kind=CANCEL,
                         tooltip="Закрыть журнал")

        self.sort_label = ctk.CTkLabel(self, text="", text_color=COL_TEXT_DIM,
                                       font=ctk.CTkFont(size=11))
        self.sort_label.pack(pady=(0, 4))
        self.count_label = ctk.CTkLabel(self, text="", text_color=COL_TEXT_LIGHT,
                                        font=ctk.CTkFont(size=11))
        self.count_label.pack(pady=(0, 2))

        self._load()

    # ---------- сортировка ----------
    def _sort_preset(self, col, desc):
        self._sort_col = col
        self._sort_desc = desc
        self._load()

    def _sort_by(self, col):
        """Клик по заголовку: переключает направление либо меняет колонку."""
        if col == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._load()

    # ---------- загрузка ----------
    def _base_query(self, session):
        q = (session.query(ECGRecord, Athlete, Device)
             .join(Athlete, ECGRecord.athlete_id == Athlete.id)
             .outerjoin(Device, ECGRecord.device_id == Device.id))
        if self.athlete_id:
            q = q.filter(ECGRecord.athlete_id == self.athlete_id)
        if self.date_from is not None and self.date_to is not None:
            dt_from = self.date_from.strftime("%Y-%m-%d %H:%M:%S")
            dt_to = self.date_to.strftime("%Y-%m-%d %H:%M:%S")
            q = q.filter(ECGRecord.recorded_at >= dt_from,
                         ECGRecord.recorded_at < dt_to)
        return q

    def _load(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        session = get_session(self.db_path)
        try:
            tbl, attr = self.SORT_ATTR[self._sort_col]
            order = attr.asc() if not self._sort_desc else attr.desc()
            q = self._base_query(session).order_by(order)
            if self.limit is not None:
                q = q.limit(self.limit)
            rows = q.all()

            for record, athlete, device in rows:
                self._insert(record, athlete, device)

            arrow = "↓" if self._sort_desc else "↑"
            self.count_label.configure(text=f"Записей: {len(rows)}")
            self.sort_label.configure(
                text=f"Сортировка: {self._sort_col} {arrow}  •  клик по заголовку меняет сортировку")
        finally:
            session.close()

    def _insert(self, rec, athlete, device):
        athlete_name = f"{athlete.last_name} {athlete.first_name} {athlete.middle_name or ''}".strip()
        device_name = f"{device.model} · {device.serial_number}" if device else "—"

        try:
            rec_at = datetime.datetime.fromisoformat(rec.recorded_at).strftime("%d.%m.%Y %H:%M")
        except Exception:
            rec_at = rec.recorded_at if rec.recorded_at else ""

        updated_str = ""
        if rec.updated_at:
            if isinstance(rec.updated_at, datetime.datetime):
                updated_str = rec.updated_at.strftime("%d.%m.%Y %H:%M")
            else:
                updated_str = str(rec.updated_at)[:16]

        sim = f"{rec.bio_similarity_pct:.0f}" if rec.bio_similarity_pct is not None else "—"

        tags = tuple([str(rec.id)])
        if rec.bio_similarity_pct is not None:
            if rec.bio_similarity_pct < BIO_SIMILARITY_CRIT_PCT:
                tags += ("crit",)
            elif rec.bio_similarity_pct < BIO_SIMILARITY_WARN_PCT:
                tags += ("warn",)

        self.tree.insert("", "end", iid=str(rec.id), tags=tags, values=(
            athlete_name, device_name, rec_at, updated_str, sim,
            f"{rec.mean_hr:.0f}" if rec.mean_hr is not None else "",
            f"{rec.rmssd:.1f}" if rec.rmssd is not None else "",
            f"{rec.sdnn:.1f}" if rec.sdnn is not None else "",
            f"{rec.stress_si:.0f}" if rec.stress_si is not None else "",
            f"{rec.tp:.0f}" if rec.tp is not None else "",
            rec.status or "",
        ))

    # ---------- действия ----------
    def _on_select(self, event=None):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_export.configure(state=state)
        self.btn_delete.configure(state=state)
        self.btn_improve.configure(state=state)

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _improve_similarity(self):
        """Открывает диалог выбора лучшего атлета для записи и переназначает её."""
        rid = self._selected_id()
        if rid is None:
            return

        def on_apply(record_id, new_athlete_id, prob):
            session = get_session(self.db_path)
            try:
                rec = session.get(ECGRecord, record_id)
                if rec is None:
                    return
                rec.athlete_id = new_athlete_id
                rec.bio_similarity_pct = round(prob * 100, 2) if prob is not None else None
                session.commit()
            finally:
                session.close()
            self._load()
            try:
                self.winfo_toplevel().event_generate("<<ECGDataChanged>>", when="tail")
            except Exception:
                pass

        from .similarity import SimilarityDialog
        SimilarityDialog(self, self.db_path, rid, on_apply=on_apply)

    def _export(self):
        rid = self._selected_id()
        if rid is None:
            return

        session = get_session(self.db_path)
        try:
            rec = session.get(ECGRecord, rid)
            if rec is None or rec.raw is None or not rec.raw.raw_data:
                messagebox.showwarning(
                    "Экспорт",
                    "Для этой записи нет сырых данных (raw_data).\n"
                    "Запись была создана без сохранения raw."
                )
                return
            rec_at = rec.recorded_at
            raw = rec.raw.raw_data
        finally:
            session.close()

        default_name = rec_at.replace(":", "-").replace(" ", "_") + ECG_FILE_EXTENSION
        path = filedialog.asksaveasfilename(
            title="Сохранить запись ЭКГ",
            initialfile=default_name,
            filetypes=[("Polar H10", f"*{ECG_FILE_EXTENSION}"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
            messagebox.showinfo("Экспорт", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")

    def _delete(self):
        rid = self._selected_id()
        if rid is None:
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранную запись ЭКГ?"):
            return

        session = get_session(self.db_path)
        try:
            rec = session.get(ECGRecord, rid)
            if rec is None:
                return
            session.delete(rec)
            session.commit()
        finally:
            session.close()

        self.tree.delete(str(rid))
        self._on_select()
        if self.on_change:
            self.on_change()
        # уведомляем главное окно (orchestrator обновит heatmap/графики)
        try:
            self.winfo_toplevel().event_generate("<<ECGDataChanged>>", when="tail")
        except Exception:
            pass