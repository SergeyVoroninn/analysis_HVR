"""ORM-модели и подключение к БД."""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Date, DateTime, Text, Boolean,
    ForeignKey, event, types, text, UniqueConstraint
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


class MetricComment(Base):
    """Комментарий пользователя к конкретной метрике за конкретную дату.

    Привязка: атлет + ключ метрики + дата записи. Один комментарий на
    (athlete_id, metric_key, comment_date). Хранится отдельно от записей ЭКГ,
    поэтому переживает пересчёт метрик и не зависит от ECGRecord.
    """
    __tablename__ = "metric_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    athlete_id = Column(String, ForeignKey("athletes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    metric_key = Column(String, nullable=False, index=True)   # "tp", "si", "hr", "rmssd"
    comment_date = Column(Date, nullable=False, index=True)   # дата записи (YYYY-MM-DD)
    comment = Column(Text, nullable=False)                    # текст комментария
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Уникальность: не более одного комментария на (атлет, метрика, дата)
    __table_args__ = (
        UniqueConstraint("athlete_id", "metric_key", "comment_date",
                         name="uq_metric_comment"),
    )


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
    - Очищает фиктивные даты рождения (значения по умолчанию старого диалога,
      например 2005-01-01), чтобы в интерфейсе не показывался неверный возраст.
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
        # Для очень старых БД (схема до разделения raw_data и появления tp/updated_at)
        # добавляем недостающие обязательные колонки, иначе обращение к модели падает.
        if "tp" not in columns:
            conn.execute(text("ALTER TABLE ecg_records ADD COLUMN tp FLOAT"))
        if "updated_at" not in columns:
            conn.execute(text("ALTER TABLE ecg_records ADD COLUMN updated_at DATETIME"))
        if "profile" in columns:
            # Устаревшая колонка-строка профиля больше не используется.
            try:
                conn.execute(text("ALTER TABLE ecg_records DROP COLUMN profile"))
            except Exception:
                pass  # старый SQLite может не поддержать DROP COLUMN
        # SDNN больше не рассчитывается и не показывается — удаляем колонку.
        if "sdnn" in columns:
            try:
                conn.execute(text("ALTER TABLE ecg_records DROP COLUMN sdnn"))
            except Exception:
                pass  # старый SQLite может не поддержать DROP COLUMN
        conn.commit()

        # У старых БД athletes.gender/birth_date хранятся как VARCHAR.
        # Значение 'M'/'F' читается и так; а вот даты рождения могли
        # проставляться по умолчанию в старом диалоге (фиктивные значения
        # вроде 2005-01-01). Очищаем их здесь же, чтобы в интерфейсе
        # не показывался неверный возраст.
        conn.execute(text("""
            UPDATE athletes
            SET birth_date = NULL
            WHERE birth_date IN ('2005-01-01','2015-01-01','2000-01-01',
                                 '1990-01-01','1980-01-01')
        """))
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

        # Бэкфилл ВРС-метрик для записей, у которых не рассчитан TP (или иные
        # метрики) — например, после открытия старой БД, где колонка tp была
        # добавлена миграцией как NULL. Метрики пересчитываются по сырой ЭКГ.
        from analysis import parse_rr, calc_metrics, calc_stress, compute_psd
        to_recompute = (
            session.query(ECGRecord)
            .join(ECGRaw, ECGRecord.id == ECGRaw.record_id)
            .options(joinedload(ECGRecord.raw))
            .filter(ECGRecord.tp.is_(None))
            .all()
        )
        for rec in to_recompute:
            raw = rec.raw.raw_data if rec.raw else ""
            try:
                rr = parse_rr(raw)
                m = calc_metrics(rr) or {}
                s = calc_stress(rr) or {}
                tp = None
                try:
                    _, _, bands = compute_psd(rr)
                    tp = bands.get("tp") if bands else None
                except Exception:
                    tp = None
                if rec.rmssd is None or "rmssd" in m:
                    rec.rmssd = m.get("rmssd")
                if rec.mean_hr is None or "mean_hr" in m:
                    rec.mean_hr = m.get("mean_hr")
                if rec.stress_si is None or "si" in s:
                    rec.stress_si = s.get("si")
                if not rec.status:
                    rec.status = m.get("status")
                rec.tp = tp
            except Exception:
                continue
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