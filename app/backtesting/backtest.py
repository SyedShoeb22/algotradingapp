
import math
import pandas as pd

from app.strategy.indicators import (
    load_candles,
    calculate_indicators
)
from app.strategy.signals import generate_signals


# -------------------------------
# BACKTEST CONFIGURATION
# -------------------------------

INITIAL_CAPITAL = 100000.0
POSITION_VALUE = 20000.0

# Illustrative cost assumption: 0.05% per side.
# Replace this with verified charges for your product
# and Angel One account before relying on results.
COST_RATE_PER_SIDE = 0.0005

SYMBOL = "SBIN-EQ"
INTERVAL = "5min"


def backtest(df):
    cash = INITIAL_CAPITAL
    position = None
    trades = []
    equity_curve = []

    for i in range(len(df)):

        # Execute the previous candle's signal at
        # the current candle's OPEN.
        if i > 0:
            previous_signal = df.iloc[i - 1]["signal"]
            current = df.iloc[i]

            execution_time = current["candle_start"]
            execution_price = float(current["open"])

            if previous_signal == "BUY" and position is None:

                quantity = math.floor(
                    POSITION_VALUE / execution_price
                )

                if quantity > 0:
                    entry_value = quantity * execution_price
                    entry_cost = entry_value * COST_RATE_PER_SIDE

                    if cash >= entry_value + entry_cost:
                        cash -= entry_value + entry_cost

                        position = {
                            "entry_time": execution_time,
                            "entry_price": execution_price,
                            "quantity": quantity,
                            "entry_cost": entry_cost
                        }

            elif previous_signal == "SELL" and position is not None:

                exit_value = (
                    position["quantity"] * execution_price
                )

                exit_cost = exit_value * COST_RATE_PER_SIDE

                cash += exit_value - exit_cost

                gross_pnl = (
                    execution_price - position["entry_price"]
                ) * position["quantity"]

                total_cost = position["entry_cost"] + exit_cost

                net_pnl = gross_pnl - total_cost

                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": execution_time,
                    "entry_price": position["entry_price"],
                    "exit_price": execution_price,
                    "quantity": position["quantity"],
                    "gross_pnl": gross_pnl,
                    "costs": total_cost,
                    "net_pnl": net_pnl,
                    "exit_reason": "SELL_SIGNAL"
                })

                position = None

        # Mark the portfolio to market at candle close.
        close_price = float(df.iloc[i]["close"])

        unrealized_value = 0.0

        if position is not None:
            unrealized_value = (
                position["quantity"] * close_price
            )

        equity = cash + unrealized_value

        equity_curve.append({
            "time": df.iloc[i]["candle_start"],
            "equity": equity
        })

    # Close any remaining position at the last available close.
    if position is not None:

        last_candle = df.iloc[-1]
        exit_price = float(last_candle["close"])

        exit_value = position["quantity"] * exit_price
        exit_cost = exit_value * COST_RATE_PER_SIDE

        cash += exit_value - exit_cost

        gross_pnl = (
            exit_price - position["entry_price"]
        ) * position["quantity"]

        total_cost = position["entry_cost"] + exit_cost
        net_pnl = gross_pnl - total_cost

        trades.append({
            "entry_time": position["entry_time"],
            "exit_time": last_candle["candle_start"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "quantity": position["quantity"],
            "gross_pnl": gross_pnl,
            "costs": total_cost,
            "net_pnl": net_pnl,
            "exit_reason": "END_OF_DATA"
        })

        equity_curve[-1]["equity"] = cash

    # -------------------------------
    # PERFORMANCE METRICS
    # -------------------------------

    trade_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve)

    total_trades = len(trade_df)

    if total_trades:
        winning_trades = int(
            (trade_df["net_pnl"] > 0).sum()
        )

        losing_trades = int(
            (trade_df["net_pnl"] <= 0).sum()
        )

        win_rate = winning_trades / total_trades * 100

        net_profit = float(trade_df["net_pnl"].sum())

        gross_profit = float(
            trade_df.loc[
                trade_df["net_pnl"] > 0, "net_pnl"
            ].sum()
        )

        gross_loss = abs(float(
            trade_df.loc[
                trade_df["net_pnl"] < 0, "net_pnl"
            ].sum()
        ))

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf") if gross_profit > 0 else 0.0
        )

        total_costs = float(trade_df["costs"].sum())

    else:
        winning_trades = 0
        losing_trades = 0
        win_rate = 0.0
        net_profit = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        profit_factor = 0.0
        total_costs = 0.0

    equity_df["peak"] = equity_df["equity"].cummax()

    equity_df["drawdown_pct"] = (
        (equity_df["equity"] - equity_df["peak"])
        / equity_df["peak"]
    ) * 100

    max_drawdown = abs(
        float(equity_df["drawdown_pct"].min())
    )

    final_capital = cash
    total_return = (
        (final_capital - INITIAL_CAPITAL)
        / INITIAL_CAPITAL
    ) * 100

    return {
        "trades": trade_df,
        "equity": equity_df,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "total_costs": total_costs,
        "net_profit": net_profit,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "final_capital": final_capital,
        "total_return": total_return
    }


def main():

    print("=" * 55)
    print("SBIN-EQ HISTORICAL BACKTEST")
    print("=" * 55)

    df = load_candles(SYMBOL, INTERVAL)

    print("Loaded candles:", len(df))

    df = calculate_indicators(df)
    df = generate_signals(df)

    print("Running backtest...")

    results = backtest(df)

    print("\nBACKTEST CONFIGURATION")
    print("Initial capital: Rs.", INITIAL_CAPITAL)
    print("Position value: Rs.", POSITION_VALUE)
    print("Estimated cost per side:", COST_RATE_PER_SIDE * 100, "%")

    print("\nPERFORMANCE RESULTS")
    print("-" * 40)

    print("Total trades:", results["total_trades"])
    print("Winning trades:", results["winning_trades"])
    print("Losing trades:", results["losing_trades"])
    print("Win rate:", round(results["win_rate"], 2), "%")
    print("Gross profit:", round(results["gross_profit"], 2))
    print("Gross loss:", round(results["gross_loss"], 2))
    print("Estimated costs:", round(results["total_costs"], 2))
    print("Net profit/loss:", round(results["net_profit"], 2))
    print("Profit factor:", round(results["profit_factor"], 3))
    print("Maximum drawdown:", round(results["max_drawdown"], 2), "%")
    print("Final capital:", round(results["final_capital"], 2))
    print("Total return:", round(results["total_return"], 2), "%")

    if not results["trades"].empty:
        print("\nTRADE HISTORY")
        print("-" * 40)

        print(
            results["trades"].to_string(index=False)
        )
    else:
        print("\nNo trades were generated by this strategy.")

    # Save results for later analysis.
    results["trades"].to_csv(
        "data/backtest_trades.csv",
        index=False
    )

    results["equity"].to_csv(
        "data/backtest_equity.csv",
        index=False
    )

    print("\nSaved:")
    print("data/backtest_trades.csv")
    print("data/backtest_equity.csv")

    print("\nBacktest completed.")


if __name__ == "__main__":
    main()

