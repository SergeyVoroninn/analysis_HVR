"""Окно «Инструкция пользователя» (открывается по F1)."""
import os

import customtkinter as ctk
from tkinter import scrolledtext
from PIL import Image, ImageTk

from theme import (COL_BG_DARK, COL_TEXT_LIGHT, COL_TEXT_DIM, COL_ACCENT)

from .base import BaseDialog, CANCEL

# Папка со скриншотами для инструкции
IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")

MAX_IMAGE_WIDTH = 600   # скриншот масштабируется под ширину окна справки
MAX_IMAGE_HEIGHT = 420

# Содержимое инструкции: список (тип, данные).
# Типы: "title" | "h2" | "p" | "img" (имя файла, подпись) | "blank"
CONTENT = [
    ("title", "ОБЗОР"),
    ("p", "Программа предназначена для просмотра и анализа записей ЭКГ "
          "(вариабельность сердечного ритма, ВСР) спортсменов. Записи снимаются "
          "нагрудным пульсометром Polar H10 и хранятся в базе данных. Окно "
          "разделено на список спортсменов слева и тепловые карты / графики справа."),

    ("h2", "СПИСОК СПОРТСМЕНОВ"),
    ("p", "Левая колонка: ＋ — добавить спортсмена, ✎ — редактировать, 🗑 — удалить. "
          "📋 Список ЭКГ — журнал записей атлета, ⬇ Импорт записи ЭКГ — загрузить "
          "одну или несколько записей. Выбор спортсмена обновляет карты и графики."),
    ("img", ("app_main.png", "Главное окно приложения")),

    ("h2", "КАРТОЧКА СПОРТСМЕНА"),
    ("p", "В окне добавления/редактирования Фамилия и Имя обязательны; пол, дата "
          "рождения, рост/вес и Polar ID — по желанию. Кнопка «Сформировать шаблон» "
          "создаёт биометрический шаблон по записям (минимум 8) для автоматического "
          "распознавания атлета и процента схожести."),
    ("img", ("athlet_edit.png", "Карточка спортсмена")),

    ("h2", "ИМПОРТ ЗАПИСЕЙ ЭКГ"),
    ("p", "Выберите один или несколько файлов .teamloggerh10. Выполняется "
          "биометрическая проверка. Если запись слабо совпадает с текущим атлетом — "
          "откроется единое окно «Биометрическое совпадение» со списком всех атлетов "
          "по убыванию схожести: укажите владельца записи или отмените импорт. Если "
          "подходящих совпадений нет — программа спросит, новый ли это человек. "
          "Дубликаты по времени импорта пропускаются."),
    ("img", ("app_import.png", "Импорт записи ЭКГ и биометрическая проверка")),

    ("h2", "НАВИГАЦИЯ ПО ВРЕМЕНИ"),
    ("p", "Год / неделя переключаются в правом окне. Тепловая карта: блок (3 часа) "
          "дня кликается для просмотра ЭКГ за интервал. Оранжевые столбики — индекс "
          "стресса, зелёные — TP. Клик по году на heatmap выделяет неделю."),
    ("img", ("year_heatmap.png", "Годовая тепловая карта")),
    ("img", ("week_heatmap.png", "Недельная тепловая карта")),

    ("h2", "ГРАФИКИ TP И ИНДЕКСА СТРЕССА"),
    ("p", "Клик, колесо мыши и перетаскивание — масштабирование и перемещение. "
          "ПКМ (правый клик) — сброс масштаба к диапазону данных."),
    ("img", ("charts.png", "Графики TP и индекса стресса")),

    ("h2", "ЖУРНАЛ ЭКГ"),
    ("p", "Колонка «Сходство» — % биологической схожести записи с шаблоном атлета "
          "(низкая подсвечивается: жёлтый < порога, красный < критического). Если "
          "сходство невозможно вычислить, вместо процента стоит короткая причина: "
          "«нет ЭКГ» (в файле только RR, без ЭКГ-сигнала), «нет шаблона» или "
          "«плохой сигн.». Сортировка — кликом по заголовку или кнопками. "
          "«🎯 Улучшить сходство» открывает список всех атлетов по убыванию схожести "
          "для переназначения записи. «🗑 Удалить» — удалить запись, "
          "«Экспорт в файл» — сохранить raw-данные."),
    ("img", ("ecg_list.png", "Журнал записей ЭКГ")),

    ("h2", "БИОМЕТРИЯ / ОПРЕДЕЛЕНИЕ АТЛЕТА"),
    ("p", "Для каждого спортсмена из его записей формируется шаблон (форма сигнала и "
          "спектр). Для сравнения используется единое окно со списком атлетов по "
          "убыванию схожести — оно же открывается по кнопке «Улучшить сходство» и "
          "при импорте слабого совпадения; выбор указывает на владельца записи. "
          "Процент схожести сохраняется в БД и автоматически дозаполняется у записей, "
          "загруженных до создания шаблона."),
    ("img", ("app_biometria.png", "Биометрическое определение атлета")),

    ("h2", "ГОРЯЧИЕ КЛАВИШИ"),
    ("p", "F1 — эта инструкция."),
]


class HelpDialog(BaseDialog):
    """Немодальное окно справки: инструкция с встроенными скриншотами."""

    def __init__(self, parent):
        super().__init__(parent, title="Инструкция пользователя",
                         size="680x560", resizable=(True, True), modal=False)

        self._images = []  # держим ссылки на PhotoImage, чтобы не удалялись сборщиком

        ctk.CTkLabel(self, text="Инструкция пользователя",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(10, 4))

        text = scrolledtext.ScrolledText(
            self, wrap="word", padx=14, pady=10,
            font=("Segoe UI", 10),
            bg=COL_BG_DARK, fg=COL_TEXT_LIGHT, insertbackground=COL_TEXT_LIGHT)
        text.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        text.tag_configure("title", font=("Segoe UI", 13, "bold"),
                           foreground=COL_TEXT_LIGHT, spacing1=6, spacing3=4)
        text.tag_configure("h2", font=("Segoe UI", 11, "bold"),
                           foreground=COL_ACCENT, spacing1=8, spacing3=2)
        text.tag_configure("body", font=("Segoe UI", 10), foreground=COL_TEXT_LIGHT)
        text.tag_configure("cap", font=("Segoe UI", 9, "italic"), foreground=COL_TEXT_DIM)

        for kind, data in CONTENT:
            if kind == "title":
                text.insert("end", data + "\n", "title")
            elif kind == "h2":
                text.insert("end", data + "\n", "h2")
            elif kind == "p":
                text.insert("end", data + "\n\n", "body")
            elif kind == "img":
                photo = self._load_image(text, data[0], data[1])
                if photo is not None:
                    self._images.append(photo)

        text.configure(state="disabled")
        self._text = text

        self.make_button(self, "Закрыть", self.close, kind=CANCEL, side="top", pady=10,
                         tooltip="Закрыть инструкцию")

        self._center_over_parent()

    def _load_image(self, text, filename, caption):
        """Масштабирует и встраивает скриншот в текст; возвращает PhotoImage."""
        path = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(path):
            text.insert("end", f"[изображение {filename} не найдено]\n\n", "cap")
            return None
        try:
            im = Image.open(path)
            im.thumbnail((MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT), Image.LANCZOS)
            photo = ImageTk.PhotoImage(im)
            text.image_create("end", image=photo, padx=6)
            text.insert("end", "\n")
            text.insert("end", caption, "cap")
            text.insert("end", "\n\n")
            return photo
        except Exception as e:
            text.insert("end", f"[не удалось загрузить {filename}: {e}]\n\n", "cap")
            return None