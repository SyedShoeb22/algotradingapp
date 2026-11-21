"""Paper-trading engine.

For every watchlist symbol the engine:

1. Claims the newest completed candle (duplicate protection via the
   UNIQUE constraint on ``paper_processed_candles``).
2. Runs the stale-data check -- candles older than
   ``MAX_CANDLE_AGE_MINUTES`` are skipped.
3. Evaluates the strategy (EMA/RSI/MACD) on that candle.
4. Executes paper trades against the symbol's *own* paper account,
   honouring per-symbol and global risk limits.

Real order execution is never performed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.core.config import (
    GLOBAL_MAX_OPEN_POSITIONS,
    MAX_CANDLE_AGE_MINUTES,
    MIN_CANDLES_FOR_SIGNAL,
    STRATEGY_NAME,
)
from app.core.database import SessionLocal
from app.core.events import log_event
from app.core.models import (
    Candle,
    MarketTick,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ProcessedCandle,
    WatchlistSymbol,
)
from app.strategy.indicators import calculate_indicators, load_candles
from app.strategy.signals import signal_for_row


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _latest_fresh_live_tick(db, symbol: str, max_age_seconds: int = 5):
    """Return a fresh NSE tick only for the active LIVE engine and token."""
    try:
        from app.paper.runner import get_engine
        engine = get_engine()
        if engine is None or engine.simulate:
            return None
    except Exception:
        return None

    watch = (
        db.query(WatchlistSymbol)
        .filter(WatchlistSymbol.symbol == symbol)
        .first()
    )
    if not watch or not watch.token or str(watch.token).startswith("SIM-"):
        return None

    cutoff = _utcnow() - timedelta(seconds=max_age_seconds)
    return (
        db.query(MarketTick)
        .filter(
            MarketTick.symbol == symbol,
            MarketTick.token == str(watch.token),
            MarketTick.exchange == "NSE",
            MarketTick.ltp > 0,
            MarketTick.received_at >= cutoff,
        )
        .order_by(MarketTick.received_at.desc())
        .first()
    )


def _claim_candle(db, symbol: str, interval: str, candle_start) -> bool:
    """Atomically claim a candle. False => already processed (duplicate)."""

    db.add(
        ProcessedCandle(
            symbol=symbol,
            interval=interval,
            candle_start=candle_start,
            signal="PENDING",
        )
    )
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _set_claimed_signal(db, symbol, interval, candle_start, signal):
    row = (
        db.query(ProcessedCandle)
        .filter_by(
            symbol=symbol,
            interval=interval,
            candle_start=candle_start,
        )
        .first()
    )
    if row:
        row.signal = signal
        db.commit()


def open_position_count(db) -> int:
    return (
        db.query(PaperPosition)
        .filter(PaperPosition.quantity > 0)
        .count()
    )


def evaluate_symbol(
    symbol: str,
    interval: str = "5min",
    db=None,
) -> dict:
    """Evaluate one symbol on its newest completed candle.

    Returns a result dict with ``status`` in
    {TRADED, SIGNAL_ONLY, DUPLICATE, STALE, NO_DATA, WARMUP, SKIPPED, ERROR}.
    """

    own_session = db is None
    db = db or SessionLocal()

    try:
        entry = (
            db.query(WatchlistSymbol)
            .filter(
                WatchlistSymbol.symbol == symbol,
                WatchlistSymbol.interval == interval,
            )
            .first()
        )
        if entry is None or not entry.enabled:
            return {"status": "SKIPPED", "reason": "symbol not enabled"}

        latest = (
            db.query(Candle)
            .filter(
                Candle.symbol == symbol,
                Candle.interval == interval,
            )
            .order_by(Candle.candle_start.desc())
            .first()
        )
        if latest is None:
            return {"status": "NO_DATA", "reason": "no candles yet"}

        # ---- Stale-data check -------------------------------------
        age_minutes = (_utcnow() - latest.candle_start).total_seconds() / 60
        if age_minutes > MAX_CANDLE_AGE_MINUTES:
            log_event(
                "WARN", "paper",
                f"{symbol}: skipped stale candle "
                f"{latest.candle_start} (age {age_minutes:.1f} min)",
            )
            return {
                "status": "STALE",
                "reason": f"candle age {age_minutes:.1f} min",
            }

        # ---- Indicators / signal -----------------------------------
        df = calculate_indicators(load_candles(symbol, interval, days=10))
        df = df[df["candle_start"] <= latest.candle_start]

        if len(df) < MIN_CANDLES_FOR_SIGNAL:
            if not _claim_candle(db, symbol, interval, latest.candle_start):
                return {"status": "DUPLICATE", "reason": "candle already processed"}
            _set_claimed_signal(db, symbol, interval, latest.candle_start, "HOLD")
            return {
                "status": "WARMUP",
                "reason": f"only {len(df)} candles (need {MIN_CANDLES_FOR_SIGNAL})",
            }

        row = df.iloc[-1]
        signal, reason = signal_for_row(row)
        candle_price = float(row["close"])

        live_tick = None
        if signal in ("BUY", "SELL"):
            live_tick = _latest_fresh_live_tick(db, symbol)
            if live_tick is None:
                return {
                    "status": "STALE_PRICE",
                    "signal": signal,
                    "reason": "No fresh matching LIVE NSE tick (max age 5 seconds)",
                    "candle_start": str(latest.candle_start),
                }
            price = round(float(live_tick.ltp), 2)
        else:
            price = candle_price

        if not _claim_candle(db, symbol, interval, latest.candle_start):
            return {"status": "DUPLICATE", "reason": "candle already processed"}

        _set_claimed_signal(db, symbol, interval, latest.candle_start, signal)

        result = {
            "status": "SIGNAL_ONLY",
            "signal": signal,
            "reason": reason,
            "price": price,
            "candle_start": str(latest.candle_start),
        }

        if signal == "HOLD":
            hold_tick = _latest_fresh_live_tick(db, symbol)
            if hold_tick is not None:
                _mark_position_price(db, symbol, round(float(hold_tick.ltp), 2))
            return result

        # ---- Execution against the symbol's own paper account ------
        # (queried inside THIS session; never mix sessions mid-trade)
        account = (
            db.query(PaperAccount)
            .filter(PaperAccount.symbol == symbol)
            .first()
        )
        if account is None:
            account = PaperAccount(
                symbol=symbol,
                initial_capital=entry.initial_capital,
                cash=entry.initial_capital,
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            log_event(
                "INFO", "paper",
                f"Opened paper account for {symbol} "
                f"with Rs.{entry.initial_capital:,.0f}",
            )

        position = (
            db.query(PaperPosition)
            .filter(PaperPosition.symbol == symbol)
            .first()
        )

        if signal == "BUY":
            if position is not None and position.quantity > 0:
                return result  # already invested; HOLD effectively
            if open_position_count(db) >= GLOBAL_MAX_OPEN_POSITIONS:
                log_event(
                    "WARN", "paper",
                    f"{symbol}: BUY rejected - global limit of "
                    f"{GLOBAL_MAX_OPEN_POSITIONS} open positions reached",
                )
                return {**result, "status": "SKIPPED",
                        "reason": "global position limit reached"}

            budget = min(entry.max_position_value,
                           account.cash * entry.max_position_pct)
            quantity = int(budget // price)
            if quantity < 1:
                log_event(
                    "WARN", "paper",
                    f"{symbol}: BUY rejected - insufficient cash "
                    f"(cash={account.cash:.2f}, price={price:.2f})",
                )
                return {**result, "status": "SKIPPED",
                        "reason": "insufficient cash"}

            trade_value = round(quantity * price, 2)
            account.cash = round(account.cash - trade_value, 2)
            account.updated_at = _utcnow()

            if position is None:
                position = PaperPosition(symbol=symbol, quantity=0)
                db.add(position)
            position.quantity = quantity
            position.average_price = price
            position.last_price = price
            position.unrealized_pnl = 0.0
            position.opened_at = position.opened_at or _utcnow()
            position.updated_at = _utcnow()

            db.add(
                PaperTrade(
                    symbol=symbol,
                    side="BUY",
                    quantity=quantity,
                    price=price,
                    trade_value=trade_value,
                    signal_candle=latest.candle_start,
                    strategy=STRATEGY_NAME,
                    status="PAPER",
                )
            )
            db.commit()

            log_event(
                "INFO", "paper",
                f"{symbol}: BUY {quantity} @ {price:.2f} "
                f"(value Rs.{trade_value:,.0f})",
            )
            return {
                **result,
                "status": "TRADED",
                "quantity": quantity,
                "cash": account.cash,
            }

        if signal == "SELL":
            if position is None or position.quantity <= 0:
                return result  # nothing to exit

            quantity = position.quantity
            trade_value = round(quantity * price, 2)
            pnl = round((price - (position.average_price or price)) * quantity, 2)

            account.cash = round(account.cash + trade_value, 2)
            account.realized_pnl = round(account.realized_pnl + pnl, 2)
            account.updated_at = _utcnow()

            position.quantity = 0
            position.unrealized_pnl = 0.0
            position.last_price = price
            position.updated_at = _utcnow()

            db.add(
                PaperTrade(
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    price=price,
                    trade_value=trade_value,
                    pnl=pnl,
                    signal_candle=latest.candle_start,
                    strategy=STRATEGY_NAME,
                    status="PAPER",
                )
            )
            db.commit()

            log_event(
                "INFO", "paper",
                f"{symbol}: SELL {quantity} @ {price:.2f} "
                f"(P&L Rs.{pnl:+,.0f})",
            )
            return {
                **result,
                "status": "TRADED",
                "quantity": quantity,
                "pnl": pnl,
                "cash": account.cash,
            }

        return result

    except Exception as error:  # noqa: BLE001
        db.rollback()
        log_event("ERROR", "paper", f"{symbol} evaluation failed: {error}")
        return {"status": "ERROR", "reason": str(error)}

    finally:
        if own_session:
            db.close()


def _mark_position_price(db, symbol: str, price: float):
    position = (
        db.query(PaperPosition)
        .filter(PaperPosition.symbol == symbol)
        .first()
    )
    if position and position.quantity > 0:
        position.last_price = price
        if position.average_price:
            position.unrealized_pnl = round(
                (price - position.average_price) * position.quantity, 2
            )
        db.commit()


def refresh_position_prices():
    """Mark open positions only from fresh, matching LIVE NSE ticks."""

    with SessionLocal() as db:
        positions = (
            db.query(PaperPosition)
            .filter(PaperPosition.quantity > 0)
            .all()
        )
        if not positions:
            return

        changed = False
        for position in positions:
            tick = _latest_fresh_live_tick(db, position.symbol)
            if tick is None:
                continue

            position.last_price = round(float(tick.ltp), 2)
            if position.average_price:
                position.unrealized_pnl = round(
                    (position.last_price - position.average_price)
                    * position.quantity,
                    2,
                )
            changed = True

        if changed:
            db.commit()


def evaluate_all(interval: str = "5min") -> dict[str, dict]:
    """Evaluate every enabled watchlist symbol once."""

    with SessionLocal() as db:
        symbols = [
            row.symbol
            for row in db.query(WatchlistSymbol)
            .filter(
                WatchlistSymbol.enabled == 1,
                WatchlistSymbol.interval == interval,
            )
            .all()
        ]

    return {symbol: evaluate_symbol(symbol, interval) for symbol in symbols}


def normalize_symbol(symbol: str) -> str:
    """Normalize user-entered symbol, e.g. TCS -> TCS-EQ if not suffixed."""
    s = symbol.strip().upper()
    if not s:
        raise ValueError("Symbol cannot be empty")
    with SessionLocal() as db:
        exact = db.query(WatchlistSymbol).filter(WatchlistSymbol.symbol == s).first()
        if exact:
            return exact.symbol
        if "-" not in s:
            suffixed = db.query(WatchlistSymbol).filter(WatchlistSymbol.symbol == f"{s}-EQ").first()
            if suffixed:
                return suffixed.symbol
            return f"{s}-EQ"
    return s


def get_current_stock_price(symbol: str, db=None) -> float:
    """Get the current LTP for a symbol from ticks, candles, or anchor price."""
    own_session = db is None
    db = db or SessionLocal()
    try:
        tick = (
            db.query(MarketTick)
            .filter(MarketTick.symbol == symbol)
            .order_by(MarketTick.received_at.desc())
            .first()
        )
        if tick and tick.ltp and tick.ltp > 0:
            return round(tick.ltp, 2)

        candle = (
            db.query(Candle)
            .filter(Candle.symbol == symbol)
            .order_by(Candle.candle_start.desc())
            .first()
        )
        if candle and candle.close and candle.close > 0:
            return round(candle.close, 2)

        from app.broker.collector import SimulatedFeed
        return round(SimulatedFeed.get_anchor_price(symbol), 2)
    finally:
        if own_session:
            db.close()


def execute_paper_order(
    symbol: str,
    side: str,
    quantity: int,
    price: float | None = None,
    strategy: str = "MANUAL",
    enable_auto_trading: bool | None = False,
    initial_capital: float = 100000.0,
    db=None,
) -> dict:
    """Execute an immediate paper trade for the specified stock.
    
    Creates/updates paper account, position, and trade history.
    Never executes real broker orders.
    """
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0")

    side = side.strip().upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Invalid order side: {side}. Must be BUY or SELL")

    norm_symbol = normalize_symbol(symbol)
    own_session = db is None
    db = db or SessionLocal()

    try:
        # 1. Ensure WatchlistSymbol exists
        watchlist_entry = (
            db.query(WatchlistSymbol)
            .filter(WatchlistSymbol.symbol == norm_symbol)
            .first()
        )
        if not watchlist_entry:
            token = f"SIM-{norm_symbol.split('-')[0]}"
            token_status = "OK"
            try:
                from app.broker.instruments import InstrumentResolver
                resolver = InstrumentResolver()
                resolved = resolver.resolve_token(norm_symbol, "NSE")
                if resolved:
                    token = resolved
            except Exception:
                pass

            watchlist_entry = WatchlistSymbol(
                symbol=norm_symbol,
                exchange="NSE",
                interval="5min",
                token=token,
                token_status=token_status,
                enabled=1 if enable_auto_trading else 0,
                initial_capital=initial_capital,
                max_position_value=50000.0,
                max_position_pct=0.5,
            )
            db.add(watchlist_entry)
            db.commit()
            db.refresh(watchlist_entry)

            try:
                from app.paper.runner import get_engine
                engine = get_engine()
                if engine:
                    engine.ensure_symbol_registered(norm_symbol, watchlist_entry.token)
            except Exception:
                pass
        elif enable_auto_trading and watchlist_entry.enabled == 0:
            watchlist_entry.enabled = 1
            db.commit()

        # 2. Validate execution mode and price BEFORE creating/updating account.
        try:
            from app.paper.runner import get_engine
            active_engine = get_engine()
        except Exception as exc:
            raise ValueError(f"Cannot verify trading mode: {exc}") from exc

        if active_engine is None:
            raise ValueError("Trading engine is not running; paper order rejected.")

        live_mode = not active_engine.simulate
        live_tick = None

        if live_mode:
            live_tick = _latest_fresh_live_tick(db, norm_symbol)
            if live_tick is None:
                raise ValueError(
                    "LIVE paper order rejected: no fresh matching NSE tick "
                    "(maximum age 5 seconds)."
                )

        # 2. Ensure PaperAccount exists
        account = (
            db.query(PaperAccount)
            .filter(PaperAccount.symbol == norm_symbol)
            .first()
        )
        if not account:
            account = PaperAccount(
                symbol=norm_symbol,
                initial_capital=initial_capital,
                cash=initial_capital,
                realized_pnl=0.0,
            )
            db.add(account)
            db.commit()
            db.refresh(account)

        # 3. Get / ensure PaperPosition
        position = (
            db.query(PaperPosition)
            .filter(PaperPosition.symbol == norm_symbol)
            .first()
        )
        if not position:
            position = PaperPosition(
                symbol=norm_symbol,
                quantity=0,
                average_price=0.0,
                last_price=0.0,
                unrealized_pnl=0.0,
            )
            db.add(position)
            db.commit()
            db.refresh(position)

        # 4. Resolve execution price
        # LIVE fills always use the validated Angel One tick.
        # User-supplied prices and candle/simulated fallbacks are SIMULATION-only.
        if live_mode:
            exec_price = round(float(live_tick.ltp), 2)
        else:
            exec_price = float(
                price if price and price > 0
                else get_current_stock_price(norm_symbol, db)
            )
        trade_value = round(quantity * exec_price, 2)

        # 5. Execute BUY or SELL
        if side == "BUY":
            if account.cash < trade_value:
                raise ValueError(
                    f"Insufficient paper cash: required ₹{trade_value:,.2f}, available ₹{account.cash:,.2f}"
                )

            account.cash = round(account.cash - trade_value, 2)
            account.updated_at = _utcnow()

            old_qty = position.quantity or 0
            new_qty = old_qty + quantity
            old_cost = (position.average_price or 0.0) * old_qty
            new_cost = exec_price * quantity
            new_avg = round((old_cost + new_cost) / new_qty, 2)

            position.quantity = new_qty
            position.average_price = new_avg
            position.last_price = exec_price
            position.unrealized_pnl = round((exec_price - new_avg) * new_qty, 2)
            position.updated_at = _utcnow()
            if not position.opened_at:
                position.opened_at = _utcnow()

            trade = PaperTrade(
                symbol=norm_symbol,
                side="BUY",
                quantity=quantity,
                price=exec_price,
                trade_value=trade_value,
                pnl=None,
                strategy=strategy,
                status="PAPER",
                executed_at=_utcnow(),
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            log_event(
                "INFO", "paper",
                f"[{strategy}] {norm_symbol}: BUY {quantity} @ {exec_price:.2f} (Total Rs.{trade_value:,.2f})"
            )

        else:  # SELL
            if (position.quantity or 0) <= 0:
                raise ValueError(f"No open position in {norm_symbol} to sell")
            if quantity > position.quantity:
                raise ValueError(
                    f"Cannot sell {quantity} shares; current holding is {position.quantity} shares of {norm_symbol}"
                )

            avg_price = position.average_price or exec_price
            pnl = round((exec_price - avg_price) * quantity, 2)

            account.cash = round(account.cash + trade_value, 2)
            account.realized_pnl = round(account.realized_pnl + pnl, 2)
            account.updated_at = _utcnow()

            new_qty = position.quantity - quantity
            position.quantity = new_qty
            position.last_price = exec_price
            if new_qty == 0:
                position.average_price = 0.0
                position.unrealized_pnl = 0.0
            else:
                position.unrealized_pnl = round((exec_price - position.average_price) * new_qty, 2)
            position.updated_at = _utcnow()

            trade = PaperTrade(
                symbol=norm_symbol,
                side="SELL",
                quantity=quantity,
                price=exec_price,
                trade_value=trade_value,
                pnl=pnl,
                strategy=strategy,
                status="PAPER",
                executed_at=_utcnow(),
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)

            log_event(
                "INFO", "paper",
                f"[{strategy}] {norm_symbol}: SELL {quantity} @ {exec_price:.2f} (P&L Rs.{pnl:+,.2f})"
            )

        return {
            "success": True,
            "trade": {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": trade.price,
                "trade_value": trade.trade_value,
                "pnl": trade.pnl,
                "strategy": trade.strategy,
                "executed_at": str(trade.executed_at),
            },
            "account": {
                "symbol": account.symbol,
                "initial_capital": account.initial_capital,
                "cash": account.cash,
                "realized_pnl": account.realized_pnl,
            },
            "position": {
                "quantity": position.quantity,
                "average_price": position.average_price,
                "last_price": position.last_price,
                "unrealized_pnl": position.unrealized_pnl,
            },
        }

    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


def get_stock_quote(symbol: str) -> dict:
    """Get current price, account and position for a symbol."""
    norm_symbol = normalize_symbol(symbol)
    with SessionLocal() as db:
        price = get_current_stock_price(norm_symbol, db)
        watchlist_entry = (
            db.query(WatchlistSymbol)
            .filter(WatchlistSymbol.symbol == norm_symbol)
            .first()
        )
        account = (
            db.query(PaperAccount)
            .filter(PaperAccount.symbol == norm_symbol)
            .first()
        )
        position = (
            db.query(PaperPosition)
            .filter(PaperPosition.symbol == norm_symbol)
            .first()
        )

        return {
            "symbol": norm_symbol,
            "input_symbol": symbol.strip().upper(),
            "price": price,
            "exists_in_watchlist": watchlist_entry is not None,
            "auto_trading_enabled": bool(watchlist_entry.enabled) if watchlist_entry else False,
            "account": {
                "initial_capital": account.initial_capital if account else 100000.0,
                "cash": account.cash if account else 100000.0,
                "realized_pnl": account.realized_pnl if account else 0.0,
            },
            "position": (
                {
                    "quantity": position.quantity,
                    "average_price": position.average_price,
                    "last_price": price,
                    "unrealized_pnl": position.unrealized_pnl,
                }
                if position and position.quantity > 0
                else None
            ),
        }
