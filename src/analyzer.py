"""
analyzer.py — анализатор метрик ВСР.
Принимает ID записи ЭКГ или дату, возвращает структурированный анализ.
"""
import datetime
from dataclasses import dataclass
from typing import Optional

from models import get_session, ECGRecord, Athlete
# ИМПОРТИРУЕМ централизованный конфиг с порогами
from analysis import cfg 


@dataclass
class MetricAnalysis:
    """Результат анализа одной записи ЭКГ."""
    athlete_name: str
    recorded_at: datetime.datetime
    tp: float
    stress_si: float
    rmssd: float
    sdnn: float
    mean_hr: float
    
    tp_status: str
    tp_color: str
    stress_status: str
    stress_color: str
    
    recommendation: str
    detailed_comment: str
    
    def to_text(self) -> str:
        """Форматирует анализ в читаемый текст."""
        return (f"📊 Анализ ВСР | {self.athlete_name}\n"
                f"📅 {self.recorded_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"{'─' * 50}\n"
                f"{self.tp_color} TP: {self.tp:.0f} мс² — {self.tp_status}\n"
                f"{self.stress_color} Стресс: {self.stress_si:.0f} у.е. — {self.stress_status}\n"
                f"💓 ЧСС: {self.mean_hr:.0f} уд/мин | RMSSD: {self.rmssd:.0f} мс | SDNN: {self.sdnn:.0f} мс\n"
                f"{'─' * 50}\n"
                f"💡 {self.recommendation}\n\n"
                f"📝 {self.detailed_comment}")


class MetricAnalyzer:
    """Анализатор метрик вариабельности сердечного ритма."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def analyze(self, ecg_record_id: int) -> Optional[MetricAnalysis]:
        session = get_session(self.db_path)
        try:
            record = session.query(ECGRecord).filter(ECGRecord.id == ecg_record_id).first()
            if not record:
                return None
            
            athlete = session.query(Athlete).filter(Athlete.id == record.athlete_id).first()
            athlete_name = f"{athlete.last_name} {athlete.first_name}" if athlete else "Неизвестно"
            return self._analyze_record(record, athlete_name)
        finally:
            session.close()
    
    def analyze_by_date(self, athlete_id: str, recorded_at: str) -> Optional[MetricAnalysis]:
        session = get_session(self.db_path)
        try:
            record = session.query(ECGRecord).filter(
                ECGRecord.athlete_id == athlete_id,
                ECGRecord.recorded_at == recorded_at
            ).first()
            if not record:
                return None
            
            athlete = session.query(Athlete).filter(Athlete.id == athlete_id).first()
            athlete_name = f"{athlete.last_name} {athlete.first_name}" if athlete else "Неизвестно"
            return self._analyze_record(record, athlete_name)
        finally:
            session.close()
    
    def _analyze_record(self, record: ECGRecord, athlete_name: str) -> MetricAnalysis:
        """Внутренний метод анализа записи с использованием cfg."""
        tp = record.tp or 0.0
        si = record.stress_si or 0.0
        rmssd = record.rmssd or 0.0
        sdnn = record.sdnn or 0.0
        mean_hr = record.mean_hr or 0.0
        
        # Анализ TP (используем cfg.TP_THRESHOLDS)
        th_tp = cfg.TP_THRESHOLDS
        if tp >= th_tp["excellent"]:
            tp_status, tp_color = "Отличный ресурс", "🟢"
            tp_comment = "Организм полностью восстановлен, адаптационные системы работают оптимально."
        elif tp >= th_tp["good"]:
            tp_status, tp_color = "Хороший ресурс", "🟢"
            tp_comment = "Нервная система стабильна, ресурс достаточен для тренировочной нагрузки."
        elif tp >= th_tp["moderate"]:
            tp_status, tp_color = "Умеренный ресурс", "🟠"
            tp_comment = "Адаптационные возможности снижены. Рекомендуется легкая нагрузка."
        elif tp >= th_tp["low"]:
            tp_status, tp_color = "Низкий ресурс", "🔴"
            tp_comment = "Организм истощен. Необходим отдых, снижение нагрузки на 50-70%."
        else:
            tp_status, tp_color = "Критическое истощение", "⛔"
            tp_comment = "Полное истощение адаптационных систем. Требуется полный покой 3-5 дней."
        
        # Анализ SI (используем cfg.SI_THRESHOLDS)
        th_si = cfg.SI_THRESHOLDS
        if si <= th_si["low"]:
            stress_status, stress_color = "Норма", "🟢"
            stress_comment = "Парасимпатическая система доминирует, регуляция сбалансирована."
        elif si <= th_si["moderate"]:
            stress_status, stress_color = "Повышен", "🟠"
            stress_comment = "Симпатическая система активирована. Возможны усталость или стресс."
        elif si <= th_si["high"]:
            stress_status, stress_color = "Высокий", "🔴"
            stress_comment = "Выраженное перенапряжение регуляторных систем. Риск срыва адаптации."
        else:
            stress_status, stress_color = "Критический", "⛔"
            stress_comment = "Острый стресс или патологическое состояние. Требуется внимание."
        
        # Комбинированная рекомендация (пороги также взяты из конфига для консистентности)
        if tp >= th_tp["excellent"] and si <= th_si["low"]:
            recommendation = "💪 Идеальное состояние! Можно проводить интенсивную тренировку или соревнование."
        elif tp >= th_tp["good"] and si <= th_si["low"]:
            recommendation = "✅ Хорошее состояние. Поддерживайте текущий режим тренировок."
        elif tp < th_tp["moderate"] and si > th_si["moderate"]:
            recommendation = "🚨 КРИЗИС! Немедленный полный покой. Риск перетренированности или болезни."
        elif tp < th_tp["moderate"]:
            recommendation = "⚠️ Низкий ресурс. Снижайте нагрузку, приоритет — сон и восстановление."
        elif si > th_si["moderate"]:
            recommendation = "⚠️ Высокий стресс. Используйте дыхательные практики, избегайте стимуляторов."
        else:
            recommendation = "👍 Умеренное состояние. Мониторинг продолжается."
        
        detailed_comment = f"{tp_comment}\n{stress_comment}"
        
        return MetricAnalysis(
            athlete_name=athlete_name,
            recorded_at=datetime.datetime.fromisoformat(record.recorded_at),
            tp=tp, stress_si=si, rmssd=rmssd, sdnn=sdnn, mean_hr=mean_hr,
            tp_status=tp_status, tp_color=tp_color,
            stress_status=stress_status, stress_color=stress_color,
            recommendation=recommendation, detailed_comment=detailed_comment
        )