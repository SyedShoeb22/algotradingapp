from app.strategy.indicators import load_candles, calculate_indicators


def generate_signals(df):
    df = df.copy()

    df["signal"] = "HOLD"
    df["reason"] = "Conditions not aligned"

    required = [
        "ema_20", "ema_50", "rsi_14",
        "macd", "macd_signal"
    ]

    for index, row in df.iterrows():
        if row[required].isna().any():
            continue

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
            df.at[index, "signal"] = "BUY"
            df.at[index, "reason"] = "Bullish EMA, RSI and MACD confirmation"
        elif bearish:
            df.at[index, "signal"] = "SELL"
            df.at[index, "reason"] = "Bearish EMA, RSI and MACD confirmation"
        else:
            df.at[index, "reason"] = "EMA, RSI and MACD are not fully aligned"

    return df


def main():
    symbol = "KROSS-EQ"

    df = load_candles(symbol, "5min")
    if df.empty:
        print("No candles found.")
        return

    df = calculate_indicators(df)
    df = generate_signals(df)

    columns = [
        "candle_start", "close", "ema_20", "ema_50",
        "rsi_14", "macd", "macd_signal", "signal", "reason"
    ]

    print(df[columns].tail(10).round(3).to_string(index=False))

    latest = df.iloc[-1]
    print("\nLATEST KROSS SIGNAL")
    print("Candle:", latest["candle_start"])
    print("Price:", latest["close"])
    print("Signal:", latest["signal"])
    print("Reason:", latest["reason"])


if __name__ == "__main__":
    main()
