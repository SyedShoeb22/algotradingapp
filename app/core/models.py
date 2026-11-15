
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime
)

from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), default="NSE")
    side = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    strategy = Column(String(100), nullable=True)
    status = Column(String(20), default="PAPER")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    broker_order_id = Column(String(100), nullable=True)
    symbol = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(20), nullable=True)
    price = Column(Float, nullable=True)
    status = Column(String(30), default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), default="NSE")
    quantity = Column(Integer, default=0)
    average_price = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime, timezone


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id = Column(Integer, primary_key=True, index=True)

    symbol = Column(String(50), nullable=False, index=True)
    token = Column(String(30), nullable=False)
    exchange = Column(String(20), nullable=False)

    ltp = Column(Float, nullable=False)

    exchange_timestamp = Column(String(50), nullable=True)

    received_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

