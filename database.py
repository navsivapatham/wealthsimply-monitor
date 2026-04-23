from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    Boolean, DateTime, Date, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DB_PATH

Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, nullable=False)
    company_name = Column(String)
    average_cost = Column(Float)
    shares = Column(Float, default=0)
    source = Column(String, nullable=False)
    account_id = Column(String)
    target_price = Column(Float)
    sma_threshold = Column(Float, default=5.0)
    is_watchlist = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("symbol", "date"),)

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)


class PollingLog(Base):
    __tablename__ = "polling_log"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    current_price = Column(Float)
    sma_50 = Column(Float)
    sma_200 = Column(Float)
    distance_from_sma_50 = Column(Float)
    distance_from_avg_cost = Column(Float)
    signal = Column(String)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    signal_type = Column(String, nullable=False)
    current_price = Column(Float)
    trigger_value = Column(Float)
    message = Column(Text)
    status = Column(String, default="pending")
    notified = Column(Boolean, default=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return Session()


def get_preference(key, default=None):
    session = Session()
    try:
        pref = session.query(UserPreference).filter_by(key=key).first()
        return pref.value if pref else default
    finally:
        session.close()


def set_preference(key, value):
    session = Session()
    try:
        pref = session.query(UserPreference).filter_by(key=key).first()
        if pref:
            pref.value = str(value)
            pref.updated_at = datetime.utcnow()
        else:
            session.add(UserPreference(key=key, value=str(value)))
        session.commit()
    finally:
        session.close()
