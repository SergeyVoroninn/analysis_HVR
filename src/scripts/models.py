"""ORM-модели проекта (аналог @Entity в Hibernate)."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Index,
    create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Athlete(Base):
    __tablename__ = "athletes"

    id = Column(String, primary_key=True)
    last_name = Column(String)
    first_name = Column(String)
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

    records = relationship("ECGRecord", back_populates="athlete",
                           cascade="all, delete-orphan")

    @property
    def fio(self) -> str:
        return f"{self.last_name} {self.first_name}"


class ECGRecord(Base):
    __tablename__ = "ecg_records"

    __table_args__ = (
        Index("idx_ecg_athlete", "athlete_id"),
        Index("idx_ecg_time",    "recorded_at"),
        Index("idx_ecg_cover",   "athlete_id", "recorded_at", "sdnn", "status"),
        Index("idx_ecg_cover2",  "athlete_id", "recorded_at", "sdnn", "status", "stress_si"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(String, ForeignKey("athletes.id"), nullable=False)
    recorded_at = Column(String, nullable=False)
    duration_seconds = Column(Float)
    profile = Column(String)
    raw_data = Column(String)
    mean_hr = Column(Float)
    rmssd = Column(Float)
    sdnn = Column(Float)
    status = Column(String)
    stress_si = Column(Float)
    created_at = Column(DateTime, default=datetime.now)

    athlete = relationship("Athlete", back_populates="records")


_engine = None
_SessionLocal = None


def get_session(db_path: str):
    """Возвращает сессию SQLAlchemy (создаёт БД и таблицы если их нет)."""
    global _engine, _SessionLocal
    url = f"sqlite:///{db_path}"
    if _engine is None or str(_engine.url) != url:
        _engine = create_engine(url, echo=False)
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine)
    return _SessionLocal()