"""SQLAlchemy models for the unified trading system.

Design notes
------------
* ``WatchlistSymbol`` is the single place that maps an NSE symbol to its
  broker token and to its own paper-trading capital configuration.
* ``PaperAccount`` / ``PaperPosition`` are kept **per symbol** so every
  stock trades with its own isolated capital, as required.
* ``ProcessedCandle`` carries a UNIQUE constraint that gives duplicate-
  candle protection at the database level (the paper engine inserts a row
  per evaluated candle inside a transaction).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------
# Market data
# ------------------------------------------------------------------
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
        default=utcnow,
        nullable=False,
        index=True,
    )


class Candle(Base):
    __tablename__ = "candles"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "candle_start",
            name="uq_candle_symbol_interval_start",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    interval = Column(String(10), nullable=False)
    candle_start = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    tick_count = Column(Integer, default=0, nullable=False)
    volume = Column(Integer, nullable=False, default=0)


# ------------------------------------------------------------------
# Watchlist / symbol configuration
# ------------------------------------------------------------------
class WatchlistSymbol(Base):
    __tablename__ = "watchlist_symbols"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "exchange",
            "interval",
            name="uq_watchlist_symbol_exchange_interval",
        ),
    )

    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), nullable=False, index=True)  # e.g. SBIN-EQ
    exchange = Column(String(20), default="NSE", nullable=False)
    interval = Column(String(10), default="5min", nullable=False)
    token = Column(String(30), nullable=True)  # resolved dynamically
    token_status = Column(String(30), default="UNRESOLVED")  # OK / UNRESOLVED
    enabled = Column(Integer, default=1, nullable=False)

    # Per-stock paper capital configuration.
    initial_capital = Column(Float, default=100000.0, nullable=False)
    max_position_value = Column(Float, default=20000.0, nullable=False)
    max_position_pct = Column(Float, default=0.20, nullable=False)

    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


# ------------------------------------------------------------------
# Paper trading (per symbol)
# ------------------------------------------------------------------
class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), unique=True, nullable=False, index=True)
    initial_capital = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), unique=True, nullable=False, index=True)
    quantity = Column(Integer, default=0, nullable=False)
    average_price = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    opened_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY / SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    trade_value = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True)  # set on closing SELL
    signal_candle = Column(DateTime, nullable=True)
    strategy = Column(String(100), nullable=True)
    status = Column(String(20), default="PAPER")
    executed_at = Column(DateTime, default=utcnow, nullable=False)


class ProcessedCandle(Base):
    """One row per (symbol, interval, candle_start) the strategy has seen.

    The UNIQUE constraint is the duplicate-candle protection: the engine
    claims the candle by inserting a row, and a conflict means the candle
    was already evaluated.
    """

    __tablename__ = "paper_processed_candles"

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "candle_start",
            name="uq_processed_symbol_interval_start",
        ),
    )

    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), nullable=False, index=True)
    interval = Column(String(10), nullable=False)
    candle_start = Column(DateTime, nullable=False)
    signal = Column(String(20), default="HOLD", nullable=False)
    processed_at = Column(DateTime, default=utcnow, nullable=False)


# ------------------------------------------------------------------
# System events / audit log
# ------------------------------------------------------------------
class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True)
    level = Column(String(10), default="INFO", nullable=False)
    source = Column(String(50), nullable=False, index=True)
    message = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
