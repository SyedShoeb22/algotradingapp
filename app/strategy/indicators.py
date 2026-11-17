
import sqlite3
import pandas as pd

DB_PATH = "data/algo_trading.db"


def load_candles(symbol="SBIN-EQ", interval="5min"):
    """Load historical candles from SQLite."""

    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT candle_start, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND interval = ?
        ORDER BY candle_start ASC
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(symbol, interval)
    )

    conn.close()

    if df.empty:
        raise ValueError(f"No candles found for {symbol} ({interval})")

    df["candle_start"] = pd.to_datetime(df["candle_start"])

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["close"]).reset_index(drop=True)

    return df


def calculate_indicators(df):
    """Calculate EMA, RSI and MACD."""

    df = df.copy()

    # Exponential Moving Averages
    df["ema_20"] = df["close"].ewm(
        span=20,
        adjust=False,
        min_periods=20
    ).mean()

    df["ema_50"] = df["close"].ewm(
        span=50,
        adjust=False,
        min_periods=50
    ).mean()

    # RSI (14) using Wilder's smoothing
    delta = df["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    rs = avg_gain / avg_loss

    df["rsi_14"] = 100 - (100 / (1 + rs))

    # Handle a continuous rise or flat market
    df.loc[(avg_loss == 0) & (avg_gain > 0), "rsi_14"] = 100
    df.loc[(avg_loss == 0) & (avg_gain == 0), "rsi_14"] = 50

    # MACD (12, 26, 9)
    ema_12 = df["close"].ewm(
        span=12,
        adjust=False,
        min_periods=12
    ).mean()

    ema_26 = df["close"].ewm(
        span=26,
        adjust=False,
        min_periods=26
    ).mean()

    df["macd"] = ema_12 - ema_26

    df["macd_signal"] = df["macd"].ewm(
        span=9,
        adjust=False,
        min_periods=9
    ).mean()

    df["macd_histogram"] = df["macd"] - df["macd_signal"]

    return df


def main():
    print("Loading SBIN-EQ candles...")

    df = load_candles()

    print(f"Loaded {len(df)} candles.")

    print("Calculating technical indicators...")

    df = calculate_indicators(df)

    columns = [
        "candle_start",
        "close",
        "ema_20",
        "ema_50",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_histogram"
    ]

    print("\nLatest 10 indicator readings:\n")

    print(
        df[columns]
        .tail(10)
        .round(3)
        .to_string(index=False)
    )

    print("\nIndicator calculation completed.")


if __name__ == "__main__":
    main()

