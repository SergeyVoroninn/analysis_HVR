"""Пакет диалоговых окон приложения.

Публичный API сохраняет обратную совместимость: прежние `from dialogs import ...`
продолжают работать.
"""
from .common import _ForegroundDateEntry, ToolTip
from .athlete import AthleteDialog
from .ecg_journal import ECGJournal
from .similarity import SimilarityDialog
from .help import HelpDialog
from .settings import MetricsSettingsDialog
from .comment import CommentDialog

__all__ = [
    "AthleteDialog",
    "ECGJournal",
    "SimilarityDialog",
    "HelpDialog",
    "MetricsSettingsDialog",
    "CommentDialog",
    "ToolTip",
    "_ForegroundDateEntry",
]