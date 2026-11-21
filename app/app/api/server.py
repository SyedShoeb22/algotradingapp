"""FastAPI backend for the trading dashboard.

Serves the REST API consumed by the React dashboard and (in production)
the built frontend from ``dist/``. The API is a thin read/write layer
over the same SQLite database the engine uses, plus engine control
(start/stop) and on-demand backtests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core import watchlist as watchlist_service
from app.core.config import (
    BASE_DIR,
    GLOBAL_MAX_OPEN_POSITIONS,
    MAX_CANDLE_AGE_MINUTES,
    WEB_BUILD_DIR,
    angel_credentials_configured,
)
from app.core.database import SessionLocal, initialize_database
from app.core.models import (
    Candle,
    MarketTick,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ProcessedCandle,
    SystemEvent,
    WatchlistSymbol,
)
from app.paper.runner import get_engine, start_engine, stop_engine
from app.strategy.backtest import run_backtest
from app.strategy.indicators import calculate_indicators, load_candles
from app.strategy.signals import generate_signals

app = FastAPI(title="NSE Paper Trading Desk", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    exchange: str = "NSE"
    interval: str = "5min"
    initial_capital: float = 100000.0
    max_position_value: float = 20000.0
    max_position_pct: float = 0.20


class WatchlistPatchRequest(BaseModel):
    enabled: Optional[bool] = None
    initial_capital: Optional[float] = Field(None, gt=0)
    max_position_value: Optional[float] = Field(None, gt=0)
    max_position_pct: Optional[float] = Field(None, gt=0, le=1)


class EngineStartRequest(BaseModel):
    simulate: bool = False


class HistoryImportRequest(BaseModel):
    symbol: str
    days: int = Field(5, ge=1, le=100)


class PaperTradeOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    side: str = Field(..., min_length=3, max_length=4)
    quantity: int = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0)
    enable_auto_trading: Optional[bool] = False
    initial_capital: float = Field(100000.0, gt=0)


# ----------------------------------------------------------------------
# Health / status / engine control
# ----------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nse-paper-trading-desk"}


@app.get("/api/status")
def status():
    engine = get_engine()
    if engine is None:
        return {
            "mode": "STOPPED",
            "running": False,
            "collector": {"type": "none", "connected": False,
                          "symbols": [], "ticks_received": 0,
                          "ticks_written": 0},
            "uptime_seconds": 0,
            "symbols": _watchlist_snapshot(),
        }
    return engine.status()


def _watchlist_snapshot():
    """Full per-symbol snapshot; safe to call whether or not the engine runs."""
    with SessionLocal() as db:
        entries = db.query(WatchlistSymbol).all()

        result = []
        for e in entries:
            last_tick = (
                db.query(MarketTick)
                .filter(MarketTick.symbol == e.symbol)
                .order_by(MarketTick.received_at.desc())
                .first()
            )
            last_candle = (
                db.query(Candle)
                .filter(
                    Candle.symbol == e.symbol,
                    Candle.interval == e.interval,
                )
                .order_by(Candle.candle_start.desc())
                .first()
            )
            account = (
                db.query(PaperAccount)
                .filter(PaperAccount.symbol == e.symbol)
                .first()
            )
            position = (
                db.query(PaperPosition)
                .filter(PaperPosition.symbol == e.symbol)
                .first()
            )

            age = None
            if last_candle:
                age = round(
                    (
                        datetime.now(timezone.utc).replace(tzinfo=None)
                        - last_candle.candle_start
                    ).total_seconds()
                    / 60,
                    1,
                )

            result.append(
                {
                    "symbol": e.symbol,
                    "exchange": e.exchange,
                    "interval": e.interval,
                    "token": e.token,
                    "token_status": e.token_status,
                    "enabled": bool(e.enabled),
                    "last_price": last_tick.ltp if last_tick else None,
                    "last_tick_at": str(last_tick.received_at) if last_tick else None,
                    "last_candle_start": str(last_candle.candle_start)
                    if last_candle
                    else None,
                    "last_candle_age_min": age,
                    "candle_count": last_candle.tick_count if last_candle else 0,
                    "account": {
                        "initial_capital": account.initial_capital
                        if account
                        else e.initial_capital,
                        "cash": account.cash if account else None,
                        "realized_pnl": account.realized_pnl if account else 0.0,
                    },
                    "position": (
                        {
                            "quantity": position.quantity,
                            "average_price": position.average_price,
                            "last_price": position.last_price,
                            "unrealized_pnl": position.unrealized_pnl,
                        }
                        if position and position.quantity > 0
                        else None
                    ),
                    "last_signal": None,
                    "last_evaluation": None,
                    "last_evaluation_reason": None,
                }
            )
        return result


@app.post("/api/engine/start")
def engine_start(payload: EngineStartRequest):
    engine = get_engine()
    if engine is not None:
        return {"status": "already_running", "mode": engine.mode}
    try:
        engine = start_engine(simulate=payload.simulate)
        return {"status": "started", "mode": engine.mode}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/engine/stop")
def engine_stop():
    engine = get_engine()
    if engine is None:
        return {"status": "already_stopped"}
    stop_engine()
    return {"status": "stopped"}


# ----------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------
@app.get("/api/watchlist")
def watchlist():
    return {"symbols": _watchlist_snapshot()}


@app.post("/api/watchlist")
def watchlist_add(payload: WatchlistAddRequest):
    resolver = None
    try:
        from app.broker.instruments import InstrumentResolver

        resolver = InstrumentResolver()
    except Exception:  # noqa: BLE001 - master file missing is fine
        resolver = None

    try:
        entry = watchlist_service.add_symbol(
            symbol=payload.symbol,
            interval=payload.interval,
            exchange=payload.exchange,
            initial_capital=payload.initial_capital,
            max_position_value=payload.max_position_value,
            max_position_pct=payload.max_position_pct,
            resolver=resolver,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return {
        "symbol": entry.symbol,
        "token": entry.token,
        "token_status": entry.token_status,
    }


@app.patch("/api/watchlist/{symbol}")
def watchlist_patch(symbol: str, payload: WatchlistPatchRequest):
    with SessionLocal() as db:
        entry = (
            db.query(WatchlistSymbol)
            .filter(WatchlistSymbol.symbol == symbol.upper())
            .first()
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Symbol not found")

        if payload.enabled is not None:
            entry.enabled = 1 if payload.enabled else 0
        if payload.initial_capital is not None:
            entry.initial_capital = payload.initial_capital
            account = (
                db.query(PaperAccount)
                .filter(PaperAccount.symbol == entry.symbol)
                .first()
            )
            if account:
                account.initial_capital = payload.initial_capital
                account.cash = payload.initial_capital
                account.realized_pnl = 0.0
        if payload.max_position_value is not None:
            entry.max_position_value = payload.max_position_value
        if payload.max_position_pct is not None:
            entry.max_position_pct = payload.max_position_pct

        db.commit()

    return {"status": "updated", "symbol": symbol.upper()}


@app.delete("/api/watchlist/{symbol}")
def watchlist_delete(symbol: str):
    if not watchlist_service.remove_symbol(symbol):
        raise HTTPException(status_code=404, detail="Symbol not found")
    return {"status": "removed", "symbol": symbol.upper()}


@app.post("/api/watchlist/resolve")
def watchlist_resolve():
    try:
        from app.broker.instruments import InstrumentResolver

        resolver = InstrumentResolver()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Scrip master unavailable: {error}. "
            "Run: python3 -m app.main instruments",
        ) from error

    results = watchlist_service.resolve_watchlist_tokens(
        resolver, only_unresolved=False
    )
    return {"resolved": results}


# ----------------------------------------------------------------------
# Paper trading data
# ----------------------------------------------------------------------
@app.get("/api/accounts")
def accounts():
    with SessionLocal() as db:
        account_rows = db.query(PaperAccount).all()
        position_rows = {
            p.symbol: p for p in db.query(PaperPosition).all()
        }

        result = []
        for account in account_rows:
            position = position_rows.get(account.symbol)
            result.append(
                {
                    "symbol": account.symbol,
                    "initial_capital": account.initial_capital,
                    "cash": account.cash,
                    "realized_pnl": account.realized_pnl,
                    "position_value": round(
                        position.quantity * (position.last_price or 0), 2
                    )
                    if position and position.quantity > 0
                    else 0.0,
                    "position": {
                        "quantity": position.quantity,
                        "average_price": position.average_price,
                        "last_price": position.last_price,
                        "unrealized_pnl": position.unrealized_pnl,
                    }
                    if position and position.quantity > 0
                    else None,
                }
            )
    return {"accounts": result}


@app.get("/api/trades")
def trades(
    symbol: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    with SessionLocal() as db:
        query = db.query(PaperTrade).order_by(
            PaperTrade.executed_at.desc()
        )
        if symbol:
            query = query.filter(PaperTrade.symbol == symbol.upper())
        rows = query.limit(limit).all()

        return {
            "trades": [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "trade_value": t.trade_value,
                    "pnl": t.pnl,
                    "strategy": t.strategy,
                    "executed_at": str(t.executed_at),
                }
                for t in rows
            ]
        }


@app.post("/api/paper/trade")
def paper_trade(payload: PaperTradeOrderRequest):
    """Execute a manual paper trade for a stock (e.g. TCS)."""
    try:
        from app.paper.engine import execute_paper_order
        result = execute_paper_order(
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            price=payload.price,
            strategy="MANUAL",
            enable_auto_trading=payload.enable_auto_trading,
            initial_capital=payload.initial_capital,
        )
        return result
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/paper/quote/{symbol}")
def paper_quote(symbol: str):
    """Get current price, paper account cash and position for a stock."""
    try:
        from app.paper.engine import get_stock_quote
        return get_stock_quote(symbol)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/symbols/popular")
def popular_symbols():
    """Return common NSE stocks for quick selection in the UI."""
    return {
        "symbols": [
            {"symbol": "TCS", "full_symbol": "TCS-EQ", "name": "Tata Consultancy Services", "sector": "IT", "anchor": 4150.0},
            {"symbol": "RELIANCE", "full_symbol": "RELIANCE-EQ", "name": "Reliance Industries", "sector": "Conglomerate", "anchor": 2980.0},
            {"symbol": "INFY", "full_symbol": "INFY-EQ", "name": "Infosys", "sector": "IT", "anchor": 1890.0},
            {"symbol": "SBIN", "full_symbol": "SBIN-EQ", "name": "State Bank of India", "sector": "Banking", "anchor": 820.0},
            {"symbol": "HDFCBANK", "full_symbol": "HDFCBANK-EQ", "name": "HDFC Bank", "sector": "Banking", "anchor": 1680.0},
            {"symbol": "TATAMOTORS", "full_symbol": "TATAMOTORS-EQ", "name": "Tata Motors", "sector": "Auto", "anchor": 980.0},
            {"symbol": "ICICIBANK", "full_symbol": "ICICIBANK-EQ", "name": "ICICI Bank", "sector": "Banking", "anchor": 1250.0},
            {"symbol": "WIPRO", "full_symbol": "WIPRO-EQ", "name": "Wipro", "sector": "IT", "anchor": 560.0},
            {"symbol": "KROSS", "full_symbol": "KROSS-EQ", "name": "Kross", "sector": "Auto Ancillary", "anchor": 252.0},
            {"symbol": "LT", "full_symbol": "LT-EQ", "name": "Larsen & Toubro", "sector": "Infrastructure", "anchor": 3620.0},
            {"symbol": "ITC", "full_symbol": "ITC-EQ", "name": "ITC", "sector": "FMCG", "anchor": 475.0},
            {"symbol": "BHARTIARTL", "full_symbol": "BHARTIARTL-EQ", "name": "Bharti Airtel", "sector": "Telecom", "anchor": 1580.0},
        ]
    }


@app.get("/api/candles/{symbol}")
def candles(
    symbol: str,
    interval: str = "5min",
    limit: int = Query(300, ge=1, le=1000),
):
    with SessionLocal() as db:
        rows = (
            db.query(Candle)
            .filter(
                Candle.symbol == symbol.upper(),
                Candle.interval == interval,
            )
            .order_by(Candle.candle_start.desc())
            .limit(limit)
            .all()
        )

        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "candles": [
                {
                    "time": str(c.candle_start),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in reversed(rows)
            ],
        }


@app.get("/api/signals/{symbol}")
def signals(symbol: str, interval: str = "5min", limit: int = 100):
    with SessionLocal() as db:
        rows = (
            db.query(ProcessedCandle)
            .filter(
                ProcessedCandle.symbol == symbol.upper(),
                ProcessedCandle.interval == interval,
            )
            .order_by(ProcessedCandle.candle_start.desc())
            .limit(limit)
            .all()
        )
        return {
            "symbol": symbol.upper(),
            "signals": [
                {
                    "candle_start": str(r.candle_start),
                    "signal": r.signal,
                    "processed_at": str(r.processed_at),
                }
                for r in reversed(rows)
            ],
        }


@app.get("/api/events")
def events(limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        rows = (
            db.query(SystemEvent)
            .order_by(SystemEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "events": [
                {
                    "id": e.id,
                    "level": e.level,
                    "source": e.source,
                    "message": e.message,
                    "created_at": str(e.created_at),
                }
                for e in rows
            ]
        }


# ----------------------------------------------------------------------
# History import / backtest / config
# ----------------------------------------------------------------------
@app.post("/api/history/import")
def history_import(payload: HistoryImportRequest):
    if not angel_credentials_configured():
        raise HTTPException(
            status_code=400,
            detail="Angel One credentials missing. Fill in .env first.",
        )

    with SessionLocal() as db:
        entry = (
            db.query(WatchlistSymbol)
            .filter(WatchlistSymbol.symbol == payload.symbol.upper())
            .first()
        )
    if not entry or not entry.token:
        raise HTTPException(
            status_code=404,
            detail=f"{payload.symbol} not in watchlist or token unresolved",
        )

    try:
        from app.broker.angel_one import connect_angel_one
        from app.broker.historical import import_historical_candles

        session = connect_angel_one()
        count = import_historical_candles(
            session["smart_api"],
            entry.symbol,
            entry.token,
            interval=entry.interval,
            days=payload.days,
            exchange=entry.exchange,
        )
        return {"status": "ok", "candles": count}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/backtest/{symbol}")
def backtest(
    symbol: str,
    interval: str = "5min",
    days: int = Query(30, ge=1, le=180),
    capital: float = Query(100000.0, gt=0),
    max_position_value: float = Query(20000.0, gt=0),
    max_position_pct: float = Query(0.20, gt=0, le=1),
):
    try:
        result = run_backtest(
            symbol.upper(),
            interval=interval,
            days=days,
            initial_capital=capital,
            max_position_value=max_position_value,
            max_position_pct=max_position_pct,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return {
        "symbol": result.symbol,
        "interval": result.interval,
        "initial_capital": result.initial_capital,
        "final_equity": result.final_equity,
        "total_return_pct": result.total_return_pct,
        "buy_signals": result.buy_signals,
        "sell_signals": result.sell_signals,
        "trades": result.trades[-100:],
        "equity_curve": result.equity_curve,
    }


@app.get("/api/indicators/{symbol}")
def indicators(symbol: str, interval: str = "5min", limit: int = 120):
    df = load_candles(symbol.upper(), interval, days=10)
    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No candles stored for {symbol.upper()} ({interval})",
        )
    df = calculate_indicators(df)
    df = generate_signals(df)
    tail = df.tail(limit)

    return {
        "symbol": symbol.upper(),
        "rows": [
            {
                "time": str(r.candle_start),
                "close": round(float(r.close), 2),
                "ema_20": None if r.ema_20 != r.ema_20 else round(float(r.ema_20), 3),
                "ema_50": None if r.ema_50 != r.ema_50 else round(float(r.ema_50), 3),
                "rsi_14": None if r.rsi_14 != r.rsi_14 else round(float(r.rsi_14), 2),
                "macd": None if r.macd != r.macd else round(float(r.macd), 4),
                "macd_signal": None if r.macd_signal != r.macd_signal else round(float(r.macd_signal), 4),
                "signal": r.signal,
                "reason": r.reason,
            }
            for r in tail.itertuples()
        ],
    }


@app.get("/api/config")
def config_info():
    engine = get_engine()
    return {
        "mode": engine.mode if engine else "STOPPED",
        "running": engine is not None,
        "simulate": bool(engine and engine.simulate),
        "angel_credentials_configured": angel_credentials_configured(),
        "risk": {
            "max_candle_age_minutes": MAX_CANDLE_AGE_MINUTES,
            "global_max_open_positions": GLOBAL_MAX_OPEN_POSITIONS,
        },
        "project_root": str(BASE_DIR),
    }


# ----------------------------------------------------------------------
# Static frontend (production build) - mounted last
# ----------------------------------------------------------------------
if WEB_BUILD_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(WEB_BUILD_DIR), html=True),
        name="web",
    )
else:
    @app.get("/")
    def index():
        return JSONResponse(
            {
                "message": "Dashboard build not found. "
                "Run: npm install && npm run build, then restart."
            }
        )
