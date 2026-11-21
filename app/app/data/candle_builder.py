"""Generic OHLC candle builder -- one implementation for all symbols.

Ticks are resampled per (symbol, interval). Only *completed* candles are
written; the currently forming candle is excluded so the strategy never
acts on partial data. Writes are idempotent upserts keyed on
(symbol, interval, candle_start), which doubles as duplicate-candle
protection at the storage layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import INTERVALS
from app.core.database import SessionLocal
from app.core.events import log_event
from app.core.models import Candle, MarketTick, WatchlistSymbol

TICK_LOOKBACK = timedelta(hours=48)


def load_ticks(symbol: str) -> pd.DataFrame:
    """Load recent ticks for one symbol."""

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - TICK_LOOKBACK

    with SessionLocal() as db:
        ticks = (
            db.query(MarketTick)
            .filter(
                MarketTick.symbol == symbol,
                MarketTick.received_at >= cutoff,
            )
            .order_by(MarketTick.received_at.asc())
            .all()
        )

        if not ticks:
            return pd.DataFrame()

        return pd.DataFrame(
            [
                {"received_at": t.received_at, "ltp": t.ltp}
                for t in ticks
            ]
        )


def generate_candles(
    df: pd.DataFrame, symbol: str, interval: str, rule: str
) -> pd.DataFrame:
    """Build completed OHLC candles from ticks."""

    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["received_at"] = pd.to_datetime(df["received_at"], utc=True)
    df["ltp"] = pd.to_numeric(df["ltp"], errors="coerce")
    df = df.dropna(subset=["received_at", "ltp"])
    df = df[df["ltp"] > 0]

    if df.empty:
        return pd.DataFrame()

    df = df.sort_values("received_at").set_index("received_at")
    price = df["ltp"]

    candles = price.resample(rule, label="left", closed="left").ohlc()
    candles["tick_count"] = price.resample(rule, label="left", closed="left").count()
    candles = candles.dropna(subset=["open"])

    # Exclude the currently forming candle.
    current_bucket = pd.Timestamp.now(tz="UTC").floor(rule)
    candles = candles[candles.index < current_bucket]

    candles["symbol"] = symbol
    candles["interval"] = interval
    return candles.reset_index()


def save_candles(candles: pd.DataFrame) -> int:
    """Upsert candles; returns rows written."""

    if candles.empty:
        return 0

    records = []

    for _, row in candles.iterrows():
        candle_time = row["received_at"].to_pydatetime().replace(tzinfo=None)
        records.append(
            {
                "symbol": row["symbol"],
                "interval": row["interval"],
                "candle_start": candle_time,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_count": int(row["tick_count"]),
                "volume": 0,
            }
        )

    with SessionLocal() as db:
        statement = sqlite_insert(Candle).values(records)
        statement = statement.on_conflict_do_update(
            index_elements=["symbol", "interval", "candle_start"],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "tick_count": statement.excluded.tick_count,
            },
        )
        db.execute(statement)
        db.commit()

    return len(records)


def build_symbol_candles(
    symbol: str,
    intervals: dict[str, str] | None = None,
) -> dict[str, int]:
    """Build and persist candles for one symbol across all intervals."""

    intervals = intervals or INTERVALS
    result = {}

    df = load_ticks(symbol)
    if df.empty:
        return {interval: 0 for interval in intervals}

    for interval, rule in intervals.items():
        candles = generate_candles(df, symbol, interval, rule)
        result[interval] = save_candles(candles)

    return result


def build_all_candles() -> dict[str, dict[str, int]]:
    """Build candles for every enabled watchlist symbol."""

    with SessionLocal() as db:
        symbols = [
            row.symbol
            for row in db.query(WatchlistSymbol)
            .filter(WatchlistSymbol.enabled == 1)
            .all()
        ]

    summary = {}

    for symbol in symbols:
        try:
            summary[symbol] = build_symbol_candles(symbol)
        except Exception as error:  # noqa: BLE001 - keep building other symbols
            summary[symbol] = {"error": str(error)}  # type: ignore[dict-item]
            log_event("ERROR", "builder", f"{symbol} build failed: {error}")

    return summary


def latest_completed_candle(
    symbol: str, interval: str
) -> Candle | None:
    """Return the newest fully completed candle for a symbol."""

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    with SessionLocal() as db:
        return (
            db.query(Candle)
            .filter(
                Candle.symbol == symbol,
                Candle.interval == interval,
                Candle.candle_start >= cutoff,
            )
            .order_by(Candle.candle_start.desc())
            .first()
        )
