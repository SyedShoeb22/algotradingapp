
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.broker.angel_one import connect_angel_one
from app.core.database import SessionLocal
from app.core.models import Candle


# SBIN-EQ on NSE
SYMBOL = "KROSS-EQ"
TOKEN = "25252"
EXCHANGE = "NSE"

# Change these dates when importing another period.
FROM_DATE = "2026-11-09 09:15"
TO_DATE = "2026-11-13 15:30"

# Angel One supports FIVE_MINUTE for up to 100 days per request.
INTERVAL = "FIVE_MINUTE"
DB_INTERVAL = "5min"


def main():

    print("Connecting to Angel One...")

    session = connect_angel_one()
    smart_api = session["smart_api"]

    params = {
        "exchange": EXCHANGE,
        "symboltoken": TOKEN,
        "interval": INTERVAL,
        "fromdate": FROM_DATE,
        "todate": TO_DATE,
    }

    print(f"Requesting historical data for {SYMBOL}")
    print(f"Period: {FROM_DATE} to {TO_DATE}")
    print(f"Interval: {INTERVAL}")

    response = smart_api.getCandleData(params)

    if not response or response.get("status") is not True:
        message = (
            response.get("message", "Unknown API error")
            if response else "No response from Angel One"
        )
        raise RuntimeError(f"Historical API failed: {message}")

    rows = response.get("data") or []

    if not rows:
        print("The API returned no candles for this date range.")
        return

    records = []

    for row in rows:
        # Response format:
        # [timestamp, open, high, low, close, volume]

        if len(row) < 6:
            continue

        timestamp = datetime.fromisoformat(
            row[0].replace("Z", "+00:00")
        )

        # Convert API's India-time timestamp to UTC-naive,
        # matching the existing candle builder.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=ZoneInfo("Asia/Kolkata")
            )

        timestamp = timestamp.astimezone(
            timezone.utc
        ).replace(tzinfo=None)

        records.append({
            "symbol": SYMBOL,
            "interval": DB_INTERVAL,
            "candle_start": timestamp,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "tick_count": 0,
            "volume": int(row[5] or 0),
        })

    if not records:
        print("No valid candle records to save.")
        return

    db = SessionLocal()

    try:
        statement = sqlite_insert(Candle).values(records)

        statement = statement.on_conflict_do_update(
            index_elements=[
                "symbol",
                "interval",
                "candle_start",
            ],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "volume": statement.excluded.volume,
            }
        )

        db.execute(statement)
        db.commit()

        print(f"Successfully imported {len(records)} candles.")

    finally:
        db.close()

    print("Historical data import completed.")


if __name__ == "__main__":
    main()

