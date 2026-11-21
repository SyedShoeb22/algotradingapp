"""Automatic historical candle import from Angel One.

On startup (and on demand) the engine back-fills each enabled symbol
with the recent candles it needs so the strategy indicators warm up
immediately instead of waiting days for live ticks.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import HISTORICAL_INTERVAL
from app.core.database import SessionLocal
from app.core.events import log_event
from app.core.models import Candle

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


def import_historical_candles(
    smart_api,
    symbol: str,
    token: str,
    interval: str = "5min",
    days: int = 5,
    exchange: str = "NSE",
) -> int:
    """Fetch the last ``days`` of candles and upsert them.

    Returns the number of candle rows written/updated.
    """

    api_interval = HISTORICAL_INTERVAL.get(interval)
    if not api_interval:
        raise ValueError(f"Unsupported interval for history import: {interval}")

    now_ist = datetime.now(IST)
    to_date = now_ist.replace(
        hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0
    )
    from_date = (now_ist - timedelta(days=days)).replace(
        hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0
    )

    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": api_interval,
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }

    log_event(
        "INFO", "history",
        f"Importing {days}d of {symbol} {interval} candles "
        f"({from_date:%Y-%m-%d} -> {to_date:%Y-%m-%d})",
    )

    response = smart_api.getCandleData(params)

    if not response or response.get("status") is not True:
        message = (
            response.get("message", "Unknown API error")
            if response
            else "No response from Angel One"
        )
        raise RuntimeError(f"Historical API failed for {symbol}: {message}")

    rows = response.get("data") or []
    if not rows:
        log_event("WARN", "history", f"No candles returned for {symbol}")
        return 0

    records = []

    for row in rows:
        # [timestamp, open, high, low, close, volume]
        if len(row) < 6:
            continue

        timestamp = datetime.fromisoformat(row[0].replace("Z", "+00:00"))

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)

        # Store naive UTC to match the live candle builder.
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)

        records.append(
            {
                "symbol": symbol,
                "interval": interval,
                "candle_start": timestamp,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(float(row[5])),
                "tick_count": 0,
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
                "volume": statement.excluded.volume,
            },
        )
        db.execute(statement)
        db.commit()

    log_event(
        "INFO", "history",
        f"Imported {len(records)} candles for {symbol} ({interval})",
    )
    return len(records)
