import os
import tkinter as tk
import datetime
from PIL import Image, ImageTk
from theme import COL_BG_DARK, COL_TEXT_DIM

# --- 1. КАРТА СООТВЕТСТВИЯ НА 5 ИСХОДОВ С ОБРАБОТКОЙ ЦВЕТА, КАРТИНКИ И ОПИСАНИЯ ---
RECOMMENDATIONS_MAP = {
    1: {
        "title": "🚨 ИСХОД 1: ОСВОБОДИТЬ ОТ ТРЕНИРОВКИ",
        "title_color": "#FF5555",
        "text": "КРИТИЧЕСКОЕ УТОМЛЕНИЕ / СТРОГИЙ ОТДЫХ\n\nПоказатели вариабельности сердечного ритма находятся на критически низком уровне, индекс стресса резко повышен. Регуляторные системы организма перегружены.\n\nИнструкция: Полностью освободить спортсмена от физических нагрузок на сегодня. Рекомендуется пассивное восстановление: полноценный сон, легкий стретчинг, миофасциальный релиз (МФР) и контроль гидратации. Категорически исключить беговые и силовые сессии.",
        "image": "rec_1.png"
    },
    2: {
        "title": "🔄 ИСХОД 2: ВОССТАНОВИТЕЛЬНАЯ ТРЕНИРОВКА",
        "title_color": "#FF9955",
        "text": "ВОССТАНОВИТЕЛЬНАЯ АКТИВНОСТЬ\n\nОрганизм демонстрирует признаки накопленного утомления. Энергетические ресурсы ограничены, но легкое движение ускорит выведение продуктов распада и улучшит тонус.\n\nИнструкция: Исключить развивающую работу. Назначить легкую восстановительную тренировку: 30–40 минут аэробной активности в 1-й пульсовой зоне (легкий бег трусцой, велосипед, плавание), суставная гимнастика или йога. Фокус на расслаблении мышц.",
        "image": "rec_2.png"
    },
    3: {
        "title": "🔵 ИСХОД 3: СРЕДНЯЯ НАГРУЗКА",
        "title_color": "#55FFFF",
        "text": "ПЛАНОВАЯ СРЕДНЯЯ НАГРУЗКА\n\nТекущее состояние систем регуляции стабильно. Организм находится в стандартном рабочем режиме и успешно адаптируется к текущему микроциклу.\n\nИнструкция: Продолжать тренировочный процесс по намеченному плану. Разрешены стандартные аэробные и силовые нагрузки средней интенсивности (2–3 пульсовые зоны). Избегать предельных отказов и экстремальных объемов.",
        "image": "rec_3.png"
    },
    4: {
        "title": "🟢 ИСХОД 4: ПОВЫШЕНИЕ НАГРУЗКИ",
        "title_color": "#55FF55",
        "text": "ПЛИК ФОРМЫ / РАЗВИВАЮЩАЯ НАГРУЗКА\n\nПоказатели ВРС превосходные, индекс стресса минимален. Атлет находится в фазе суперкомпенсации. Организм максимально готов к тяжелому физиологическому стрессу.\n\nИнструкция: Идеальный день для ударной, развивающей или высокоинтенсивной тренировки (HIIT, интервальный бег, максимальные веса в зале, контрольные старты). Можно смело повышать тренировочный объем или интенсивность для стимуляции дальнейшего роста результатов.",
        "image": "rec_4.png"
    }
}

class RecommendationsPanel(tk.Frame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("bg", COL_BG_DARK)
        super().__init__(master, **kwargs)
        
        # --- 2. КЭШИРОВАНИЕ ИЗОБРАЖЕНИЙ ПРИ СТАРТЕ ---
        self.images_cache = {}
        current_dir = os.path.dirname(os.path.abspath(__file__))
        images_dir = os.path.join(os.path.dirname(current_dir), "docs", "images")
        
        for code, data in RECOMMENDATIONS_MAP.items():
            img_path = os.path.join(images_dir, data["image"])
            if os.path.exists(img_path):
                try:
                    pil_img = Image.open(img_path).resize((100, 100), Image.Resampling.LANCZOS)
                    self.images_cache[code] = ImageTk.PhotoImage(pil_img)
                except Exception as e:
                    print(f"[Recommendations Error] Ошибка загрузки картинки {img_path}: {e}")

        # --- 3. ВЕРСТКА ВИДЖЕТОВ ПОДВАЛА ---
        # Левый фрейм-контейнер для картинки и статуса-заголовка
        self.left_frame = tk.Frame(self, bg=COL_BG_DARK)
        self.left_frame.pack(side="left", padx=15, pady=10, fill="y")
        
        self.img_label = tk.Label(self.left_frame, bg=COL_BG_DARK)
        self.img_label.pack(side="top", pady=(5, 5))
        
        self.title_label = tk.Label(
            self.left_frame, text="📋 РЕКОМЕНДАЦИИ", 
            fg="#FFFFFF", bg=COL_BG_DARK, 
            font=("Segoe UI", 11, "bold"), anchor="center"
        )
        self.title_label.pack(side="top", fill="x")
        
        # Правый текстовый блок для развернутой инструкции
        self.text_box = tk.Text(
            self, bg="#1E1E1E", fg="#E0E0E0", 
            insertbackground="white", relief="flat",
            font=("Segoe UI", 10), wrap="word"
        )
        self.text_box.pack(side="right", fill="both", expand=True, padx=(5, 10), pady=10)
        
        self.refresh()

    def refresh(self):
        """Сброс состояния панели (метод вызывается также при смене атлета)"""
        self.title_label.config(fg="#FFFFFF", text="📋 РЕКОМЕНДАЦИИ")
        self.img_label.config(image="")
        
        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", "Выберите конкретную точку на графике или день на тепловой карте для вывода рекомендаций...")
        self.text_box.config(state="disabled")

    def update_by_date(self, date_obj, athlete_id):
        """
        Вызывается из Оркестратора. Принимает дату и явный athlete_id.
        """
        self.text_box.config(state="normal")
        self.text_box.delete("1.0", "end")
        
        if not athlete_id:
            self.text_box.insert("1.0", "Ошибка: не выбран спортсмен.")
            self.text_box.config(state="disabled")
            return

        record = None
        try:
            from database import get_db_path
            from models import get_session, ECGRecord
            
            db_path = getattr(self.master, "db_path", None) or get_db_path()
            session = get_session(db_path)
            
            if isinstance(date_obj, datetime.datetime):
                start_dt = date_obj - datetime.timedelta(minutes=90)
                end_dt = date_obj + datetime.timedelta(minutes=90)
            else:
                start_dt = datetime.datetime.combine(date_obj, datetime.time.min)
                end_dt = datetime.datetime.combine(date_obj, datetime.time.max)
                
            # 💥 ИСПРАВЛЕНИЕ 1: Меняем ECGRecord.date на ECGRecord.recorded_at
            record = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == athlete_id,
                ECGRecord.recorded_at >= start_dt,
                ECGRecord.recorded_at <= end_dt
            ).first()
            
            session.close()
        except Exception as e:
            self.text_box.insert("1.0", f"Ошибка обработки БД: {e}")
            self.text_box.config(state="disabled")
            return

        if not record:
            self.title_label.config(fg=COL_TEXT_DIM, text="📋 НЕТ ДАННЫХ")
            self.img_label.config(image="")
            self.text_box.insert("1.0", f"Записи ЭКГ за {date_obj.strftime('%d.%m.%Y')} не найдены.")
            self.text_box.config(state="disabled")
            return

        code = getattr(record, "rec_code", 0)
        
        # 💥 ИСПРАВЛЕНИЕ 2: Обрабатываем дату. 
        # Если в вашей БД recorded_at хранится как строка (String ISO), её нужно распарсить.
        # Если как DateTime объект, то strftime отработает сразу. Сделаем универсально:
        rec_date = record.recorded_at
        if isinstance(rec_date, str):
            try:
                # убираем возможные лишние пробелы и парсим ISO-формат
                rec_date = datetime.datetime.fromisoformat(rec_date.replace(" ", "T"))
            except Exception:
                rec_date = date_obj # Фолбэк, если строка кривая

        if code in RECOMMENDATIONS_MAP:
            cfg = RECOMMENDATIONS_MAP[code]
            self.title_label.config(text=cfg["title"], fg=cfg["title_color"])
            
            # Использовали исправленную переменную rec_date
            header_text = f"📅 Запись от: {rec_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            self.text_box.insert("1.0", header_text + cfg["text"])
            
            if code in self.images_cache:
                self.img_label.config(image=self.images_cache[code], text="")
            else:
                self.img_label.config(image="", text="[🖼️]")
        else:
            self.title_label.config(text="📋 КОД 0: НЕ СФОРМИРОВАНО", fg=COL_TEXT_DIM)
            header_text = f"📅 Запись от: {rec_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            self.text_box.insert("1.0", header_text + "Для данной записи рекомендации отсутствуют или еще не были рассчитаны моделью.")
            self.img_label.config(image="", text="❓")
            
        self.text_box.config(state="disabled")

    # ================= ИНТЕРФЕЙС ДЛЯ REZISE_CONTROLLER (GHOST.PY) =================
    def target_size(self, avail_w):
        return (avail_w, 150)  # Жестко заданная высота подвала

    def ghost_rects(self, w, h):
        return [(0, 0, w, h)]

    def apply_size(self, w, h):
        pass

    def ghost_shown(self): pass
    def ghost_hidden(self): pass
