"""Signal generation: EMA trend + RSI zone + MACD confirmation."""

REQUIRED_COLUMNS = ["ema_20", "ema_50", "rsi_14", "macd", "macd_signal"]


def signal_for_row(row) -> tuple[str, str]:
    """Return (signal, reason) for one indicator row."""

    if row[REQUIRED_COLUMNS].isna().any():
        return "HOLD", "Indicators warming up"

    bullish = (
        row["ema_20"] > row["ema_50"]
        and 50 < row["rsi_14"] < 70
        and row["macd"] > row["macd_signal"]
    )
    bearish = (
        row["ema_20"] < row["ema_50"]
        and 30 < row["rsi_14"] < 50
        and row["macd"] < row["macd_signal"]
    )

    if bullish:
        return "BUY", "Bullish EMA, RSI and MACD confirmation"
    if bearish:
        return "SELL", "Bearish EMA, RSI and MACD confirmation"
    return "HOLD", "EMA, RSI and MACD are not fully aligned"


def generate_signals(df):
    """Attach ``signal`` and ``reason`` columns to an indicator DataFrame."""

    df = df.copy()
    df["signal"] = "HOLD"
    df["reason"] = "Conditions not aligned"

    for index, row in df.iterrows():
        signal, reason = signal_for_row(row)
        df.at[index, "signal"] = signal
        df.at[index, "reason"] = reason

    return df
