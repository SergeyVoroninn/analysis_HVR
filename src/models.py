"""ORM-модели и подключение к БД."""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Date, DateTime, Text, Boolean,
    ForeignKey, event, types, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, joinedload

Base = declarative_base()


class GenderType(types.TypeDecorator):
    """Пол спортсмена: в БД хранится как BOOLEAN (True = мужской),
    в Python-коде остаётся строка 'M'/'F'."""
    impl = Boolean
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value == "M" or value is True

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return "M" if value else "F"


class Athlete(Base):
    __tablename__ = "athletes"

    id = Column(String, primary_key=True)
    last_name = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    middle_name = Column(String)
    gender = Column(GenderType)
    birth_date = Column(Date)
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
    
    # Связь с биометрическим шаблоном (один к одному)
    bio_template = relationship(
        "BiometricTemplate", back_populates="athlete",
        uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class ECGRecord(Base):
    __tablename__ = "ecg_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(String, ForeignKey("athletes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    recorded_at = Column(String, nullable=False, index=True)
    duration_seconds = Column(Float)
    
    # УДАЛЕНО: profile = Column(String)
    # ДОБАВЛЕНО: время создания и последнего обновления для отладки
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    mean_hr = Column(Float)
    rmssd = Column(Float)
    status = Column(String)
    stress_si = Column(Float)
    tp = Column(Float)

    # Прибор, которым сделана запись (nullable для старых записей до миграции)
    device_id = Column(Integer, ForeignKey("device.id", ondelete="SET NULL"), index=True)
    # Биологическая схожесть ЭКГ с эталонным шаблоном атлета, в % (0..100)
    bio_similarity_pct = Column(Float)
    # Причина, если биометрическое сходство не вычислено (нет ЭКГ, нет шаблона, плохой сигнал)
    bio_note = Column(String)

    athlete = relationship("Athlete", back_populates="ecg_records")
    device = relationship("Device", back_populates="ecg_records")
    
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


class BiometricTemplate(Base):
    """Хранит эталонный биометрический шаблон атлета для проверки при импорте."""
    __tablename__ = "biometric_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(String, ForeignKey("athletes.id", ondelete="CASCADE"), 
                        unique=True, nullable=False, index=True)
    
    # Храним массивы NumPy как JSON-строки (SQLite не поддерживает массивы float нативно)
    shape_template = Column(Text, nullable=False)
    spectrum_template = Column(Text, nullable=False)
    
    records_used = Column(Integer, default=0)  # Сколько записей пошло в шаблон
    created_at = Column(DateTime, default=datetime.now)

    athlete = relationship("Athlete", back_populates="bio_template")


class Device(Base):
    """Прибор (нагрудный пульсометр), которым была сделана запись ЭКГ.

    Серийный номер — это `polar_id` из шапки файла TeamLoggerH10Data.
    Модель в файле отсутствует, поэтому по умолчанию проставляется "Polar H10"
    и может быть отредактирована вручную.
    """
    __tablename__ = "device"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model = Column(String, nullable=False, default="Polar H10")
    serial_number = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)

    ecg_records = relationship("ECGRecord", back_populates="device")


# ============================================================
# ПОДКЛЮЧЕНИЕ
# ============================================================
_engine = None
_SessionLocal = None


def _extract_polar_id(raw):
    """Достаёт серийный номер прибора (polar_id) из текста сырой записи ЭКГ."""
    if not raw:
        return None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("polar_id="):
            v = line.split("=", 1)[1].strip()
            return v or None
    return None


def _migrate(engine):
    """Идемпотентная миграция схемы БД.

    - Добавляет колонки ecg_records.device_id и ecg_records.bio_similarity_pct,
      если их ещё нет (SQLite ALTER не добавляет колонки через create_all).
    - Создаёт таблицу device (на случай БД, созданной до введения модели).
    - Бэкфиллит device_id: для записей без прибора читает polar_id из ecg_raw,
      находит/создаёт Device и проставляет связь.
    Повторные запуски безопасны: колонки проверяются через PRAGMA, бэкфилл
    обрабатывает только записи с device_id IS NULL.
    """
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(ecg_records)"))}
        if "device_id" not in columns:
            conn.execute(text("ALTER TABLE ecg_records ADD COLUMN device_id INTEGER"))
        if "bio_similarity_pct" not in columns:
            conn.execute(text("ALTER TABLE ecg_records ADD COLUMN bio_similarity_pct FLOAT"))
        if "bio_note" not in columns:
            conn.execute(text("ALTER TABLE ecg_records ADD COLUMN bio_note VARCHAR"))
        # SDNN больше не рассчитывается и не показывается — удаляем колонку.
        if "sdnn" in columns:
            try:
                conn.execute(text("ALTER TABLE ecg_records DROP COLUMN sdnn"))
            except Exception:
                pass  # старый SQLite может не поддержать DROP COLUMN
        conn.commit()

    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        pending = (
            session.query(ECGRecord)
            .join(ECGRaw, ECGRecord.id == ECGRaw.record_id)
            .options(joinedload(ECGRecord.raw))
            .filter(ECGRecord.device_id.is_(None))
            .all()
        )
        for rec in pending:
            polar = _extract_polar_id(rec.raw.raw_data)
            if not polar:
                continue
            dev = session.query(Device).filter(Device.serial_number == polar).first()
            if dev is None:
                dev = Device(serial_number=polar)
                session.add(dev)
                session.flush()
            rec.device_id = dev.id
        session.commit()
    finally:
        session.close()


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
        
        # Создаст все таблицы, включая новую BiometricTemplate
        Base.metadata.create_all(_engine)

        # Идемпотентная миграция схемы (новые колонки + бэкфиллинг приборов)
        try:
            _migrate(_engine)
        except Exception:
            # Не блокируем подключение к БД, если миграция не применилась
            pass

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

    return _SessionLocal()