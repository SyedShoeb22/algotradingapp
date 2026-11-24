
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from app.core.database import BASE_DIR

load_dotenv()

# --------------------------------------------------
# SBI PAPER-TRADING CONFIGURATION
# --------------------------------------------------

DB_PATH = BASE_DIR / "data" / "algo_trading.db"

INITIAL_CAPITAL = 100000.0
MAX_POSITION_VALUE = 20000.0

SYMBOL = "SBIN-EQ"
INTERVAL = "5min"
EXCHANGE = "NSE"
TOKEN = os.getenv("SBI_TOKEN")

IST = ZoneInfo("Asia/Kolkata")

# Maximum permitted age of the last completed candle.
MAX_CANDLE_AGE_MINUTES = 10

# Maximum permitted age of a live market tick for trade execution (seconds)
MAX_TICK_STALE_SECONDS = 5

# AAOIFI Shariah Screening: Must remain empty until documented screening is complete
AAOIFI_APPROVED_SYMBOLS = frozenset()

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
# MARKET DATA & FRESHNESS VALIDATION
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


def get_latest_fresh_live_tick(
    conn,
    symbol: str,
    token: str | None = None,
    exchange: str = "NSE",
    max_age_seconds: int = MAX_TICK_STALE_SECONDS,
):
    """Retrieve and validate the most recent live tick from market_ticks.

    Guarantees:
    - Exact symbol, token, and exchange match
    - Positive valid LTP (> 0)
    - Freshness: received_at within max_age_seconds of now_utc
    - Genuinely live provenance (rejects simulated/demo prefix or missing token)
    """
    resolved_token = token if token is not None else TOKEN
    if not resolved_token or str(resolved_token).startswith("SIM-"):
        return None, f"Invalid, simulated, or missing instrument token for {symbol}"

    row = conn.execute("""
        SELECT ltp, token, exchange, received_at, exchange_timestamp
        FROM market_ticks
        WHERE symbol = ?
          AND token = ?
          AND exchange = ?
          AND ltp > 0
        ORDER BY received_at DESC
        LIMIT 1
    """, (symbol, str(resolved_token), exchange)).fetchone()

    if not row:
        return None, f"No live market ticks found for {symbol} (token={resolved_token}, exchange={exchange})"

    ltp = float(row["ltp"])
    if ltp <= 0:
        return None, f"Invalid tick LTP ({ltp}) for {symbol}"

    received_at_str = row["received_at"]
    try:
        clean_str = str(received_at_str).replace("Z", "+00:00")
        tick_time = datetime.fromisoformat(clean_str)
        if tick_time.tzinfo is not None:
            tick_time = tick_time.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None, f"Unparseable tick timestamp: {received_at_str}"

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    age_seconds = (now_utc - tick_time).total_seconds()

    if age_seconds < 0:
        age_seconds = 0

    if age_seconds > max_age_seconds:
        return None, (
            f"Market tick for {symbol} is stale ({age_seconds:.1f}s old > {max_age_seconds}s limit). "
            f"Live feed may be disconnected."
        )

    return {"ltp": ltp, "received_at": tick_time, "age_seconds": age_seconds}, "Fresh live tick verified"


def validate_candle(candle):

    if not candle:
        return False, "No SBI candles found."

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

    expected = normalize_datetime(expected_candle_start)
    latest_candle = normalize_datetime(latest["candle_start"])

    if latest_candle != expected:
        return "HOLD", (
            f"Indicator candle mismatch. "
            f"Expected {expected}, got {latest_candle}"
        )

    ema20 = latest["ema20"]
    ema50 = latest["ema50"]
    rsi = latest["rsi"]
    macd = latest["macd"]
    signal = latest["macd_signal"]

    if any(v is None for v in [ema20, ema50, rsi, macd, signal]):
        return "HOLD", "Indicators are incomplete."

    if ema20 > ema50 and rsi > 55 and macd > signal:
        return "BUY", "Bullish alignment across EMA, RSI, MACD"

    if ema20 < ema50 and rsi < 45 and macd < signal:
        return "SELL", "Bearish alignment across EMA, RSI, MACD"

    return "HOLD", "No trade setup"


# --------------------------------------------------
# POSITION LOOKUP
# --------------------------------------------------

def get_open_position(conn):

    row = conn.execute("""
        SELECT COALESCE(SUM(
            CASE
                WHEN side = 'BUY' THEN quantity
                WHEN side = 'SELL' THEN -quantity
                ELSE 0
            END
        ), 0) AS quantity
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

    if signal == "HOLD":
        print("Signal is HOLD. No trade executed.")
        return

    # Shariah Compliance Gate
    if signal == "BUY" and SYMBOL not in AAOIFI_APPROVED_SYMBOLS:
        print(f"[REJECTED] BUY blocked: {SYMBOL} is not verified in AAOIFI_APPROVED_SYMBOLS.")
        return

    conn = get_connection()

    try:
        initialize_account(conn)

        # Re-verify live tick freshness inside transaction scope
        tick_data, tick_msg = get_latest_fresh_live_tick(
            conn, SYMBOL, TOKEN, EXCHANGE, max_age_seconds=MAX_TICK_STALE_SECONDS
        )
        if not tick_data:
            print(f"[REJECTED] Paper trade aborted: {tick_msg}")
            return

        exec_price = round(float(tick_data["ltp"]), 2)
        if exec_price <= 0:
            print("Invalid execution price from live tick.")
            return

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
                min(MAX_POSITION_VALUE, account["cash"]) // exec_price
            )

            if quantity <= 0:
                print("Insufficient virtual cash.")

            else:
                value = quantity * exec_price

                conn.execute("""
                    INSERT INTO paper_trades
                    (symbol, side, quantity, price, trade_value,
                     executed_at, status)
                    VALUES (?, 'BUY', ?, ?, ?, ?, 'EXECUTED')
                """, (
                    SYMBOL,
                    quantity,
                    exec_price,
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
                    f"at Rs. {exec_price:.2f}"
                )

        elif signal == "SELL" and position > 0:

            value = position * exec_price

            conn.execute("""
                INSERT INTO paper_trades
                (symbol, side, quantity, price, trade_value,
                 executed_at, status)
                VALUES (?, 'SELL', ?, ?, ?, ?, 'EXECUTED')
            """, (
                SYMBOL,
                position,
                exec_price,
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
                f"at Rs. {exec_price:.2f}"
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

    signal, reason = get_signal(candle_start)

    print(f"Symbol: {SYMBOL}")
    print(f"Interval: {INTERVAL}")
    print(f"Latest completed candle: {candle_start}")
    print(f"Signal: {signal}")
    print(f"Reason: {reason}")

    if signal == "HOLD":
        print("Signal is HOLD. No trade executed.")
        show_account_summary()
        return

    # Shariah Compliance Gate
    if signal == "BUY" and SYMBOL not in AAOIFI_APPROVED_SYMBOLS:
        print(
            f"Paper trading skipped: BUY blocked: AAOIFI Shariah screening "
            f"is not verified for {SYMBOL}."
        )
        return

    # Live Feed Freshness Gate
    conn = get_connection()
    try:
        tick_data, tick_msg = get_latest_fresh_live_tick(
            conn, SYMBOL, TOKEN, EXCHANGE, max_age_seconds=MAX_TICK_STALE_SECONDS
        )
    finally:
        conn.close()

    if not tick_data:
        print(f"Paper trading skipped: {tick_msg}")
        return

    exec_price = round(float(tick_data["ltp"]), 2)
    print(
        f"Validated LIVE Execution Price: Rs. {exec_price:.2f} "
        f"(tick age: {tick_data['age_seconds']:.1f}s)"
    )

    execute_paper_trade(
        signal,
        exec_price,
        candle_start
    )

    show_account_summary()


if __name__ == "__main__":
    main()
