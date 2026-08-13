"""
ORM-модели и подключение к БД.
"""
import os
import sys
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, Text, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

# ============================================================
# ДЕКЛАРАТИВНАЯ БАЗА
# ============================================================
Base = declarative_base()

# ============================================================
# МОДЕЛИ
# ============================================================
class Athlete(Base):
    __tablename__ = "athletes"

    id = Column(String, primary_key=True)
    last_name = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    middle_name = Column(String)
    gender = Column(String)
    birth_date = Column(String)
    height_cm = Column(Integer)
    weight_kg = Column(Float)
    resting_hr = Column(Integer)
    max_hr = Column(Integer)
    hrv_rmssd_baseline = Column(Integer)
    avg_rr_ms = Column(Integer)
    polar_id = Column(String, unique=True)

    ecg_records = relationship(
        "ECGRecord", back_populates="athlete",
        cascade="all, delete-orphan", passive_deletes=True
    )


class ECGRecord(Base):
    __tablename__ = "ecg_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(String, ForeignKey("athletes.id", ondelete="CASCADE"),
                        nullable=False)
    recorded_at = Column(String, nullable=False, index=True)
    duration_seconds = Column(Float)
    profile = Column(String)
    raw_data = Column(Text)
    mean_hr = Column(Float)
    rmssd = Column(Float)
    sdnn = Column(Float)
    status = Column(String)
    stress_si = Column(Float)

    athlete = relationship("Athlete", back_populates="ecg_records")


# ============================================================
# ПОДКЛЮЧЕНИЕ
# ============================================================
_engine = None
_SessionLocal = None


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Включает внешние ключи для SQLite (иначе CASCADE не работает)."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session(db_path: str):
    """
    Возвращает сессию SQLAlchemy.
    Создаёт БД, таблицы и папку data/ при необходимости.
    """
    global _engine, _SessionLocal

    # === Создаём директорию для БД, если её нет ===
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    url = f"sqlite:///{db_path}"

    if _engine is None or str(_engine.url) != url:
        _engine = create_engine(url, echo=False)
        
        # === Включаем внешние ключи для SQLite ===
        if url.startswith("sqlite"):
            event.listen(_engine, "connect", _set_sqlite_pragma)
        
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine)

    return _SessionLocal()