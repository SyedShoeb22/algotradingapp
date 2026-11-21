"""Walk-forward backtest over stored candles.

Reuses the same indicators and signal rules as the live paper engine so
backtest results and live behaviour stay comparable. Position sizing
mirrors the paper engine: min(max_position_value, cash * pct).
"""

from dataclasses import dataclass, field

from app.core.config import MIN_CANDLES_FOR_SIGNAL, STRATEGY_NAME
from app.strategy.indicators import calculate_indicators, load_candles
from app.strategy.signals import generate_signals


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    buy_signals: int = 0
    sell_signals: int = 0
    candles_tested: int = 0


def run_backtest(
    symbol: str,
    interval: str = "5min",
    days: int = 30,
    initial_capital: float = 100000.0,
    max_position_value: float = 20000.0,
    max_position_pct: float = 0.20,
) -> BacktestResult:
    df = load_candles(symbol, interval, days=days)
    if df.empty:
        raise ValueError(f"No candles stored for {symbol} ({interval})")

    df = calculate_indicators(df)
    df = generate_signals(df)

    cash = initial_capital
    quantity = 0
    average_price = 0.0
    realized = 0.0
    trades: list[dict] = []
    equity_curve: list[dict] = []

    tested = 0

    for _, row in df.iterrows():
        price = float(row["close"])
        signal = row["signal"]

        if signal in ("BUY", "SELL"):
            tested += 1
            if signal == "BUY":
                if quantity == 0 and not row[["ema_20", "ema_50", "rsi_14", "macd", "macd_signal"]].isna().any():
                    budget = min(max_position_value, cash * max_position_pct)
                    qty = int(budget // price)
                    if qty >= 1:
                        cash -= qty * price
                        quantity = qty
                        average_price = price
                        trades.append(
                            {
                                "side": "BUY",
                                "quantity": qty,
                                "price": price,
                                "time": str(row["candle_start"]),
                            }
                        )
            elif signal == "SELL":
                if quantity > 0:
                    pnl = (price - average_price) * quantity
                    cash += quantity * price
                    realized += pnl
                    trades.append(
                        {
                            "side": "SELL",
                            "quantity": quantity,
                            "price": price,
                            "time": str(row["candle_start"]),
                            "pnl": round(pnl, 2),
                        }
                    )
                    quantity = 0
                    average_price = 0.0

        equity = cash + quantity * price
        equity_curve.append(
            {
                "time": str(row["candle_start"]),
                "equity": round(equity, 2),
                "close": round(price, 2),
            }
        )

    final_equity = cash + quantity * price

    return BacktestResult(
        symbol=symbol,
        interval=interval,
        initial_capital=initial_capital,
        final_equity=round(final_equity, 2),
        total_return_pct=round(
            (final_equity - initial_capital) / initial_capital * 100, 2
        ),
        trades=trades,
        equity_curve=equity_curve,
        buy_signals=sum(1 for t in trades if t["side"] == "BUY"),
        sell_signals=sum(1 for t in trades if t["side"] == "SELL"),
        candles_tested=max(tested, 0) if len(df) >= MIN_CANDLES_FOR_SIGNAL else 0,
    )
