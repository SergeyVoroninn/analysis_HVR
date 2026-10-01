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

__all__ = [
    "AthleteDialog",
    "ECGJournal",
    "SimilarityDialog",
    "HelpDialog",
    "MetricsSettingsDialog",
    "ToolTip",
    "_ForegroundDateEntry",
]