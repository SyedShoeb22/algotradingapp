
import pandas as pd

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import SessionLocal
from app.core.models import MarketTick, Candle


# SBI configuration
SYMBOL = "SBIN-EQ"

INTERVALS = {
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "1hour": "1h",
}


def load_ticks():
    """Load SBI ticks from SQLite."""

    with SessionLocal() as db:
        ticks = (
            db.query(MarketTick)
            .filter(MarketTick.symbol == SYMBOL)
            .order_by(MarketTick.received_at.asc())
            .all()
        )

        if not ticks:
            return pd.DataFrame()

        return pd.DataFrame([
            {
                "received_at": tick.received_at,
                "ltp": tick.ltp,
            }
            for tick in ticks
        ])


def generate_candles(df, interval, rule):
    """
    Generate OHLC candles using tick receipt timestamps.

    Only completed candles are returned. The currently forming
    candle is excluded to avoid premature paper-trading signals.
    """

    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    df["received_at"] = pd.to_datetime(
        df["received_at"],
        utc=True
    )

    df["ltp"] = pd.to_numeric(
        df["ltp"],
        errors="coerce"
    )

    df = df.dropna(subset=["received_at", "ltp"])
    df = df[df["ltp"] > 0]

    if df.empty:
        return pd.DataFrame()

    df = df.sort_values("received_at")
    df = df.set_index("received_at")

    price_series = df["ltp"]

    candles = price_series.resample(
        rule,
        label="left",
        closed="left"
    ).ohlc()

    counts = price_series.resample(
        rule,
        label="left",
        closed="left"
    ).count()

    candles["tick_count"] = counts

    candles = candles.dropna(subset=["open"])

    # Exclude the currently forming candle.
    current_bucket = pd.Timestamp.now(
        tz="UTC"
    ).floor(rule)

    candles = candles[
        candles.index < current_bucket
    ]

    candles["symbol"] = SYMBOL
    candles["interval"] = interval

    return candles.reset_index()


def save_candles(candles):
    """Insert or update candles without duplicating their timestamps."""

    if candles.empty:
        return 0

    records = []

    for _, row in candles.iterrows():

        candle_time = (
            row["received_at"]
            .to_pydatetime()
            .replace(tzinfo=None)
        )

        records.append({
            "symbol": row["symbol"],
            "interval": row["interval"],
            "candle_start": candle_time,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "tick_count": int(row["tick_count"]),
            # LTP WebSocket mode does not provide traded volume.
            # Do not mistake tick count for exchange volume.
            "volume": 0,
        })

    with SessionLocal() as db:

        statement = sqlite_insert(Candle).values(records)

        statement = statement.on_conflict_do_update(
            index_elements=[
                "symbol",
                "interval",
                "candle_start"
            ],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "tick_count": statement.excluded.tick_count,
                "volume": statement.excluded.volume,
            }
        )

        db.execute(statement)
        db.commit()

    return len(records)


def main():

    print("===================================")
    print("SBI CANDLE BUILDER")
    print("===================================")

    print(f"Loading {SYMBOL} market ticks...")

    df = load_ticks()

    if df.empty:
        print(f"No market ticks found for {SYMBOL}.")
        return

    print(f"Loaded {len(df)} ticks.")

    for interval, rule in INTERVALS.items():

        candles = generate_candles(
            df,
            interval,
            rule
        )

        saved = save_candles(candles)

        print(
            f"{interval}: "
            f"Completed candles: {len(candles)} | "
            f"Saved/updated: {saved}"
        )

    print("SBI candle generation completed.")


if __name__ == "__main__":
    main()

