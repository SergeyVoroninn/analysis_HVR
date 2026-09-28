"""Пакет диалоговых окон приложения.

Публичный API сохраняет обратную совместимость: прежние `from dialogs import ...`
продолжают работать.
"""
from .common import _ForegroundDateEntry, ToolTip
from .athlete import AthleteDialog
from .ecg_journal import ECGJournal
from .similarity import SimilarityDialog
from .choice import BiometricChoiceDialog
from .help import HelpDialog

__all__ = [
    "AthleteDialog",
    "ECGJournal",
    "SimilarityDialog",
    "BiometricChoiceDialog",
    "HelpDialog",
    "ToolTip",
    "_ForegroundDateEntry",
]