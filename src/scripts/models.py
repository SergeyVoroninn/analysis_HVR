"""ORM-модели и подключение к БД."""
import os
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Text,
    ForeignKey, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


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
                        nullable=False, index=True)
    recorded_at = Column(String, nullable=False, index=True)
    duration_seconds = Column(Float)
    profile = Column(String)
    # raw_data больше НЕ хранится здесь
    mean_hr = Column(Float)
    rmssd = Column(Float)
    sdnn = Column(Float)
    status = Column(String)
    stress_si = Column(Float)
    tp_spectral = Column(Float, nullable=True)
    vlf = Column(Float, nullable=True)
    lf = Column(Float, nullable=True)
    hf = Column(Float, nullable=True)
    lf_hf = Column(Float, nullable=True)    

    athlete = relationship("Athlete", back_populates="ecg_records")
    # Ленивая связь 1-к-1 с сырыми данными
    raw = relationship(
        "ECGRaw", back_populates="record",
        uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class ECGRaw(Base):
    """Тяжёлая таблица с сырыми данными ЭКГ. Загружается только при обращении."""
    __tablename__ = "ecg_raw"

    record_id = Column(
        Integer,
        ForeignKey("ecg_records.id", ondelete="CASCADE"),
        primary_key=True
    )
    raw_data = Column(Text, nullable=False)

    record = relationship("ECGRecord", back_populates="raw")


# ============================================================
# ПОДКЛЮЧЕНИЕ
# ============================================================
_engine = None
_SessionLocal = None


def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session(db_path: str):
    global _engine, _SessionLocal

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    url = f"sqlite:///{db_path}"

    if _engine is None or str(_engine.url) != url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(url, echo=False, pool_pre_ping=True)
        event.listen(_engine, "connect", _set_sqlite_pragma)
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    return _SessionLocal()