"""
app_logging.py — единое логирование приложения.

Пишет в файл <log_dir>/app.log (в exe-режиме — рядом с exe в logs/, иначе в src/logs/)
с ротацией (макс. размер x 5 backups) и дублирует в stderr. Дополнительно
перехватывает необработанные исключения (sys.excepthook) — все крэши также
попадают в файл, чтобы потом было удобно разбирать.

Хендлеры вешаются на ROOT-логгер, поэтому любой именованный логгер из
get_logger(name) корректно наследует их через propagation.
"""
import logging
import logging.handlers
import os
import sys

from database import SRC_DIR

_CONFIGURED = False


def log_path() -> str:
    """Путь к файлу лога (<base>/logs/app.log)."""
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "logs")
    else:
        base = os.path.join(SRC_DIR, "logs")  # src/logs/
    return os.path.join(base, "app.log")


def setup_logging() -> None:
    """Настраивает ROOT-логгер один раз: файл с ротацией + stderr + перехват крэшей."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    try:
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path(),
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except Exception:
        pass  # если файл не открывается — пишем только в stderr

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    # Необработанные исключения -> в лог (и в файл, и в stderr).
    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("app.crash").critical(
            "Необработанное исключение: %s: %s",
            exc_type.__name__,
            exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _excepthook


def get_logger(name="app") -> logging.Logger:
    """Возвращает логгер, настроенный один раз (файл + stderr)."""
    setup_logging()
    return logging.getLogger(name)