
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.database import BASE_DIR

# --------------------------------------------------
# KROSS PAPER-TRADING CONFIGURATION
# --------------------------------------------------

DB_PATH = BASE_DIR / "data" / "algo_trading.db"

INITIAL_CAPITAL = 100000.0
MAX_POSITION_VALUE = 20000.0

SYMBOL = "KROSS-EQ"
INTERVAL = "5min"
EXCHANGE = "NSE"

IST = ZoneInfo("Asia/Kolkata")

# Maximum permitted age of the last completed candle.
MAX_CANDLE_AGE_MINUTES = 10

STRATEGY_NAME = "EMA20_EMA50_RSI14_MACD"


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# --------------------------------------------------
# PAPER ACCOUNT INITIALIZATION
# --------------------------------------------------

def initialize_account(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            initial_capital REAL NOT NULL,
            cash REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            trade_value REAL NOT NULL,
            executed_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)

    # Records every completed candle processed by this strategy.
    # The UNIQUE constraint prevents duplicate execution.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_processed_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            candle_start TEXT NOT NULL,
            signal TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            UNIQUE(symbol, interval, candle_start)
        )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO paper_account
        (id, initial_capital, cash, created_at)
        VALUES (1, ?, ?, ?)
    """, (
        INITIAL_CAPITAL,
        INITIAL_CAPITAL,
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()


# --------------------------------------------------
# MARKET DATA
# --------------------------------------------------

def get_latest_candle():

    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT *
            FROM candles
            WHERE symbol = ?
              AND interval = ?
            ORDER BY candle_start DESC
            LIMIT 1
        """, (SYMBOL, INTERVAL)).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def normalize_datetime(value):
    """Convert timestamps to UTC-naive datetime for comparison."""

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def validate_candle(candle):

    if not candle:
        return False, "No KROSS candles found."

    if candle["tick_count"] is None or candle["tick_count"] <= 0:
        return False, "Candle has no live tick updates."

    candle_start = normalize_datetime(candle["candle_start"])

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    candle_end = candle_start + timedelta(minutes=5)

    # Never process a candle that is still forming.
    if candle_end > now_utc:
        return False, "Latest candle is still forming."

    age = now_utc - candle_end

    if age > timedelta(minutes=MAX_CANDLE_AGE_MINUTES):
        return False, (
            f"Market data is stale. Last completed candle ended "
            f"{age} ago."
        )

    # Restrict paper trading to NSE regular market hours.
    now_ist = datetime.now(IST)

    if now_ist.weekday() >= 5:
        return False, "NSE regular market is closed for the weekend."

    market_open = now_ist.replace(
        hour=9, minute=15, second=0, microsecond=0
    )

    market_close = now_ist.replace(
        hour=15, minute=30, second=0, microsecond=0
    )

    if not (market_open <= now_ist <= market_close):
        return False, "Outside NSE regular market hours."

    return True, "Candle validation successful."


# --------------------------------------------------
# STRATEGY SIGNAL
# --------------------------------------------------

def get_signal(expected_candle_start):

    from app.strategy.indicators import (
        load_candles,
        calculate_indicators
    )

    df = load_candles(SYMBOL, INTERVAL)

    if df.empty:
        return "HOLD", "No indicator data available."

    df = calculate_indicators(df)

    if len(df) < 50:
        return "HOLD", "Not enough candles for indicators."

    latest = df.iloc[-1]

    required = [
        "ema_20",
        "ema_50",
        "rsi_14",
        "macd",
        "macd_signal"
    ]

    if latest[required].isna().any():
        return "HOLD", "Indicators are not ready."

    # Ensure the indicator calculation uses the same candle
    # that passed the freshness check.
    indicator_candle_start = normalize_datetime(
        latest["candle_start"]
    )

    expected_candle_start = normalize_datetime(
        expected_candle_start
    )

    if indicator_candle_start != expected_candle_start:
        return "HOLD", "Indicator candle does not match latest candle."

    if (
        latest["ema_20"] > latest["ema_50"]
        and 50 < latest["rsi_14"] < 70
        and latest["macd"] > latest["macd_signal"]
    ):
        return "BUY", "Bullish EMA, RSI and MACD conditions."

    if (
        latest["ema_20"] < latest["ema_50"]
        and 30 < latest["rsi_14"] < 50
        and latest["macd"] < latest["macd_signal"]
    ):
        return "SELL", "Bearish EMA, RSI and MACD conditions."

    return "HOLD", "No complete trading signal."


# --------------------------------------------------
# PAPER POSITION
# --------------------------------------------------

def get_open_position(conn):

    row = conn.execute("""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN side = 'BUY' THEN quantity
                        WHEN side = 'SELL' THEN -quantity
                        ELSE 0
                    END
                ), 0
            ) AS quantity
        FROM paper_trades
        WHERE symbol = ?
          AND status = 'EXECUTED'
    """, (SYMBOL,)).fetchone()

    return int(row["quantity"])


# --------------------------------------------------
# PAPER TRADE EXECUTION
# --------------------------------------------------

def execute_paper_trade(signal, price, candle_start):

    if signal not in ("BUY", "SELL", "HOLD"):
        raise ValueError(f"Invalid signal: {signal}")

    if price <= 0:
        print("Invalid execution price.")
        return

    conn = get_connection()

    try:
        initialize_account(conn)

        # Acquire a write lock before checking whether this candle
        # has already been processed.
        conn.execute("BEGIN IMMEDIATE")

        candle_key = normalize_datetime(candle_start).isoformat()

        existing = conn.execute("""
            SELECT id
            FROM paper_processed_candles
            WHERE symbol = ?
              AND interval = ?
              AND candle_start = ?
        """, (
            SYMBOL,
            INTERVAL,
            candle_key
        )).fetchone()

        if existing:
            conn.rollback()
            print("This candle has already been processed. No duplicate trade.")
            return

        # Claim this candle. The unique constraint is an additional
        # protection against duplicate processing.
        conn.execute("""
            INSERT INTO paper_processed_candles
            (symbol, interval, candle_start, signal, processed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            SYMBOL,
            INTERVAL,
            candle_key,
            signal,
            datetime.now(timezone.utc).isoformat()
        ))

        account = conn.execute("""
            SELECT *
            FROM paper_account
            WHERE id = 1
        """).fetchone()

        position = get_open_position(conn)

        if signal == "BUY" and position == 0:

            quantity = int(
                min(MAX_POSITION_VALUE, account["cash"]) // price
            )

            if quantity <= 0:
                print("Insufficient virtual cash.")

            else:
                value = quantity * price

                conn.execute("""
                    INSERT INTO paper_trades
                    (symbol, side, quantity, price, trade_value,
                     executed_at, status)
                    VALUES (?, 'BUY', ?, ?, ?, ?, 'EXECUTED')
                """, (
                    SYMBOL,
                    quantity,
                    price,
                    value,
                    datetime.now(timezone.utc).isoformat()
                ))

                conn.execute("""
                    UPDATE paper_account
                    SET cash = cash - ?
                    WHERE id = 1
                """, (value,))

                print(
                    f"PAPER BUY: {quantity} shares "
                    f"at Rs. {price:.2f}"
                )

        elif signal == "SELL" and position > 0:

            value = position * price

            conn.execute("""
                INSERT INTO paper_trades
                (symbol, side, quantity, price, trade_value,
                 executed_at, status)
                VALUES (?, 'SELL', ?, ?, ?, ?, 'EXECUTED')
            """, (
                SYMBOL,
                position,
                price,
                value,
                datetime.now(timezone.utc).isoformat()
            ))

            conn.execute("""
                UPDATE paper_account
                SET cash = cash + ?
                WHERE id = 1
            """, (value,))

            print(
                f"PAPER SELL: {position} shares "
                f"at Rs. {price:.2f}"
            )

        else:
            print(
                f"No trade executed. Signal: {signal}, "
                f"Position: {position}"
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# --------------------------------------------------
# ACCOUNT SUMMARY
# --------------------------------------------------

def show_account_summary():

    conn = get_connection()

    try:
        initialize_account(conn)

        account = conn.execute("""
            SELECT *
            FROM paper_account
            WHERE id = 1
        """).fetchone()

        position = get_open_position(conn)

        latest_trade = conn.execute("""
            SELECT side, quantity, price, executed_at
            FROM paper_trades
            WHERE symbol = ?
              AND status = 'EXECUTED'
            ORDER BY id DESC
            LIMIT 1
        """, (SYMBOL,)).fetchone()

        print("\n========== PAPER ACCOUNT ==========")
        print(f"Symbol: {SYMBOL}")
        print(f"Initial capital: Rs. {account['initial_capital']:.2f}")
        print(f"Available cash: Rs. {account['cash']:.2f}")
        print(f"Open quantity: {position}")

        if latest_trade:
            print(
                f"Last trade: {latest_trade['side']} "
                f"{latest_trade['quantity']} "
                f"at Rs. {latest_trade['price']:.2f}"
            )

        print("===================================")

    finally:
        conn.close()


# --------------------------------------------------
# MAIN PAPER ENGINE
# --------------------------------------------------

def main():

    print("\n" + "=" * 45)
    print(f"{SYMBOL} PAPER TRADING ENGINE")
    print("=" * 45)

    candle = get_latest_candle()

    valid, message = validate_candle(candle)

    if not valid:
        print(f"Paper trading skipped: {message}")
        return

    candle_start = candle["candle_start"]
    price = float(candle["close"])

    signal, reason = get_signal(candle_start)

    print(f"Symbol: {SYMBOL}")
    print(f"Interval: {INTERVAL}")
    print(f"Latest completed candle: {candle_start}")
    print(f"Price: Rs. {price:.2f}")
    print(f"Signal: {signal}")
    print(f"Reason: {reason}")

    execute_paper_trade(
        signal,
        price,
        candle_start
    )

    show_account_summary()


if __name__ == "__main__":
    main()

