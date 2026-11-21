"""Technical indicators (EMA, RSI, MACD) and candle loading."""

import pandas as pd
from sqlalchemy import text

from app.core.database import engine

CANDLE_QUERY = text(
    """
    SELECT candle_start, open, high, low, close, volume
    FROM candles
    WHERE symbol = :symbol AND interval = :interval
      AND candle_start >= :since
    ORDER BY candle_start ASC
    """
)


def load_candles(
    symbol: str,
    interval: str = "5min",
    days: int = 30,
) -> pd.DataFrame:
    """Load candles for any symbol from SQLite."""

    since = pd.Timestamp.now() - pd.Timedelta(days=days)

    with engine.connect() as conn:
        df = pd.read_sql_query(
            CANDLE_QUERY,
            conn,
            params={
                "symbol": symbol,
                "interval": interval,
                "since": since.to_pydatetime(),
            },
        )

    if df.empty:
        return df

    df["candle_start"] = pd.to_datetime(df["candle_start"])

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate EMA(20/50), RSI(14, Wilder) and MACD(12,26,9)."""

    df = df.copy()

    df["ema_20"] = df["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    rs = avg_gain / avg_loss
    df["rsi_14"] = 100 - (100 / (1 + rs))
    df.loc[(avg_loss == 0) & (avg_gain > 0), "rsi_14"] = 100
    df.loc[(avg_loss == 0) & (avg_gain == 0), "rsi_14"] = 50

    ema_12 = df["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False, min_periods=26).mean()

    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
    df["macd_histogram"] = df["macd"] - df["macd_signal"]

    return df
