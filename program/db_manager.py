# db_manager.py
import os
import sys
import pandas as pd
import bcrypt
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Определяем базовую директорию
if getattr(sys, 'frozen', False):
    # Запущено из .exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Запущено из Python
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'polar_h10_app.db')}"

engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()

# ==========================================
# Модели данных
# ==========================================

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    recordings = relationship("Recording", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, plain_password: str):
        self.password_hash = bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, plain_password: str) -> bool:
        return bcrypt.checkpw(plain_password.encode('utf-8'), self.password_hash.encode('utf-8'))


class Recording(Base):
    __tablename__ = 'recordings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    polar_id = Column(String(50), nullable=True)
    version = Column(String(20), nullable=True)
    record_datetime = Column(String(50), nullable=True)
    
    rr_data = Column(JSON, nullable=True)
    acc_data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="recordings")
    ecg_chunks = relationship("ECGChunk", back_populates="recording", cascade="all, delete-orphan")


class ECGChunk(Base):
    __tablename__ = 'ecg_chunks'
    id = Column(Integer, primary_key=True)
    recording_id = Column(Integer, ForeignKey('recordings.id'), nullable=False)
    
    chunk_timestamp = Column(String(50), nullable=True)
    ecg_values = Column(JSON, nullable=False)
    
    recording = relationship("Recording", back_populates="ecg_chunks")

Base.metadata.create_all(engine)

# ==========================================
# Функции для работы с БД
# ==========================================

def get_or_create_default_user():
    """Возвращает данные пользователя по умолчанию в виде обычного словаря"""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        user = session.query(User).filter_by(username="default_user").first()
        if not user:
            user = User(username="default_user")
            user.set_password("123")
            session.add(user)
            session.commit()
            
        # 🟢 ЯВНО извлекаем нужные данные в обычный словарь ДО закрытия сессии.
        # Это на 100% исключает ошибку DetachedInstanceError.
        return {
            "id": user.id,
            "username": user.username
        }
    finally:
        session.close()


def save_session_to_db(user_id: int, header: dict, ecg_result, df_rr, df_acc):
    """Сохраняет загруженную сессию в базу данных (с надежным преобразованием типов)"""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Вспомогательная функция для гарантированного превращения чего угодно в плоский список чисел
        def to_flat_list(data):
            if data is None:
                return []
            if hasattr(data, 'values'):  # Это pandas DataFrame или Series
                return data.values.flatten().tolist()
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], list): # Список списков [[1], [2]]
                    return [item for sublist in data for item in sublist]
                return data # Уже плоский список
            return list(data)

        recording = Recording(
            user_id=user_id,
            polar_id=header.get("polar_id", "Unknown"),
            version=header.get("version", "1.0"),
            record_datetime=header.get("datetime", ""),
            rr_data=to_flat_list(df_rr),
            acc_data=to_flat_list(df_acc)
        )
            
        session.add(recording)
        session.flush()
        
        # Сохранение ЭКГ
        if isinstance(ecg_result, list) and len(ecg_result) > 0:
            if isinstance(ecg_result[0], dict):
                for chunk in ecg_result:
                    session.add(ECGChunk(
                        recording_id=recording.id,
                        chunk_timestamp=chunk.get("timestamp", ""),
                        ecg_values=chunk.get("values", [])
                    ))
            else:
                # Плоский список чисел
                session.add(ECGChunk(
                    recording_id=recording.id,
                    chunk_timestamp="full_session",
                    ecg_values=ecg_result
                ))
        elif hasattr(ecg_result, 'values'): # Если вдруг ecg_result это pandas Series
            session.add(ECGChunk(
                recording_id=recording.id,
                chunk_timestamp="full_session",
                ecg_values=ecg_result.values.flatten().tolist()
            ))
                
        session.commit()
        return recording.id
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_user_recordings_list(user_id: int):
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        recordings = session.query(Recording).filter_by(user_id=user_id).order_by(Recording.created_at.desc()).all()
        result = []
        for rec in recordings:
            ecg_points = len(rec.ecg_chunks[0].ecg_values) if rec.ecg_chunks else 0
            result.append({
                "id": rec.id,
                "datetime": rec.record_datetime or "Неизвестно",
                "polar_id": rec.polar_id or "Unknown",
                "ecg_points": ecg_points
            })
        session.expunge_all()
        return result
    finally:
        session.close()


def get_full_recording_by_id(record_id: int):
    """Загружает полные данные из БД и гарантирует возврат DataFrame с правильными именами колонок"""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        rec = session.query(Recording).filter_by(id=record_id).first()
        if not rec:
            return None
            
        header = {
            "polar_id": rec.polar_id,
            "version": rec.version,
            "datetime": rec.record_datetime
        }
        
        # 🟢 ИСПРАВЛЕНИЕ: Возвращаем ожидаемые имена колонок, а не 'values'
        df_rr = pd.DataFrame({'rr_ms': rec.rr_data}) if rec.rr_data else pd.DataFrame()
        df_acc = pd.DataFrame({'acc_raw': rec.acc_data}) if rec.acc_data else pd.DataFrame()
        
        # Для ЭКГ оставляем 'values', так как tab_ecg.py мы уже адаптировали под это
        all_ecg_values = []
        for chunk in rec.ecg_chunks:
            all_ecg_values.extend(chunk.ecg_values)
        ecg_result = pd.DataFrame({'values': all_ecg_values}) if all_ecg_values else pd.DataFrame()
            
        session.expunge_all()
        return header, ecg_result, df_rr, df_acc
        
    finally:
        session.close()

def is_duplicate_recording(user_id: int, polar_id: str, record_datetime: str, ecg_length: int) -> bool:
    """
    Проверяет, существует ли уже в БД запись с таким же датчиком, 
    временем и количеством точек ЭКГ.
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # 1. Ищем кандидатов по датчику и времени
        candidates = session.query(Recording).filter(
            Recording.user_id == user_id,
            Recording.polar_id == polar_id,
            Recording.record_datetime == record_datetime
        ).all()
        
        # 2. Если кандидаты есть, проверяем точное совпадение длины данных ЭКГ
        for rec in candidates:
            db_ecg_length = sum(len(chunk.ecg_values) for chunk in rec.ecg_chunks)
            if db_ecg_length == ecg_length:
                return True  # Точный дубликат найден
                
        return False
    finally:
        session.close()        

def delete_recording_by_id(record_id: int) -> bool:
    """
    Удаляет запись и все связанные с ней чанки ЭКГ из базы данных.
    Возвращает True, если удаление прошло успешно.
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        rec = session.query(Recording).filter_by(id=record_id).first()
        if not rec:
            return False
            
        # Благодаря cascade="all, delete-orphan" в модели Recording,
        # все связанные ECGChunk будут удалены автоматически.
        session.delete(rec)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()