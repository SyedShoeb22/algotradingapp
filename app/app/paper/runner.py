"""Continuous trading engine runner.

One process runs everything, in threads:

* token resolution + optional historical import (startup, once)
* a single generic market-data collector (live WebSocket or simulated)
* the candle builder loop (all symbols, every few seconds)
* the strategy evaluation loop (all symbols, every few seconds)

Subprocess orchestration from the old per-stock runners is gone --
``python3 -m app.main run`` starts this engine directly.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta, timezone

from app.broker.collector import (
    LiveMarketDataCollector,
    SimulatedFeed,
    TickWriter,
)
from app.core import watchlist as watchlist_service
from app.core.config import (
    BUILDER_LOOP_SECONDS,
    COLLECTOR_RESTART_SECONDS,
    STRATEGY_LOOP_SECONDS,
    angel_credentials_configured,
)
from app.core.database import SessionLocal, initialize_database
from app.core.events import log_event
from app.core.models import (
    Candle,
    MarketTick,
    PaperAccount,
    PaperPosition,
    WatchlistSymbol,
)
from app.data.candle_builder import build_all_candles
from app.paper.engine import evaluate_all, refresh_position_prices

SIMULATED_HISTORY_DAYS = 5
HISTORY_IMPORT_DAYS = 5


class TradingEngine:
    """Single orchestrator for collection, building and paper trading."""

    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.mode = "SIMULATION" if simulate else "LIVE"

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        self.tick_writer = TickWriter()
        self.collector = None
        self.started_at: float | None = None

        # Latest per-symbol evaluation results (for status/API).
        self.last_results: dict[str, dict] = {}
        self._last_history_import: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        initialize_database()
        watchlist_service.seed_default_watchlist()

        self.started_at = time.time()
        log_event("INFO", "engine",
                  f"Engine starting in {self.mode} mode")

        if self.simulate:
            self._prepare_simulation()
        else:
            self._prepare_live()

        self.tick_writer.start()

        with SessionLocal() as db:
            entries = (
                db.query(WatchlistSymbol)
                .filter(WatchlistSymbol.enabled == 1)
                .all()
            )
            symbol_map = {
                e.symbol: (e.token or "0")
                for e in entries
                if e.token
            }

        if not symbol_map:
            log_event(
                "ERROR", "engine",
                "No resolvable symbols in the watchlist - "
                "engine idle. Add symbols via the dashboard.",
            )

        if self.simulate:
            self.collector = SimulatedFeed(symbol_map, self.tick_writer)
        else:
            self.collector = LiveMarketDataCollector(
                symbol_map, self.tick_writer
            )

        self.collector.start()

        self._spawn(self._builder_loop, "candle-builder")
        self._spawn(self._strategy_loop, "strategy-evaluator")
        self._spawn(self._collector_watchdog, "collector-watchdog")

        log_event("INFO", "engine", "Engine started")

    def stop(self):
        log_event("INFO", "engine", "Engine stopping")
        self._stop.set()

        if self.collector:
            self.collector.stop()
        self.tick_writer.stop()

        for thread in self._threads:
            thread.join(timeout=10)

        log_event("INFO", "engine", "Engine stopped")

    def _spawn(self, target, name: str):
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------
    def _prepare_live(self):
        """Resolve tokens from the scrip master + import history."""

        from app.broker.instruments import (
            InstrumentResolver,
            download_scrip_master,
        )

        try:
            download_scrip_master()
            resolver = InstrumentResolver()
            watchlist_service.resolve_watchlist_tokens(resolver)
        except Exception as error:  # noqa: BLE001
            log_event(
                "ERROR", "engine",
                f"Token resolution failed: {error}. "
                "Run: python3 -m app.main instruments",
            )

        if not angel_credentials_configured():
            log_event(
                "WARN", "engine",
                "Angel One credentials missing - live feed unavailable.",
            )
            return

        def _import_history():
            try:
                from app.broker.angel_one import connect_angel_one
                from app.broker.historical import import_historical_candles

                session = connect_angel_one()
                with SessionLocal() as db:
                    entries = db.query(WatchlistSymbol).filter(
                        WatchlistSymbol.enabled == 1,
                        WatchlistSymbol.token.isnot(None),
                    ).all()

                for entry in entries:
                    try:
                        import_historical_candles(
                            session["smart_api"],
                            entry.symbol,
                            entry.token,
                            interval=entry.interval,
                            days=HISTORY_IMPORT_DAYS,
                            exchange=entry.exchange,
                        )
                        self._last_history_import[entry.symbol] = time.time()
                    except Exception as error:  # noqa: BLE001
                        log_event(
                            "WARN", "history",
                            f"{entry.symbol} history import failed: {error}",
                        )
            except Exception as error:  # noqa: BLE001
                log_event("ERROR", "history",
                          f"History import aborted: {error}")

        threading.Thread(
            target=_import_history, name="history-import", daemon=True
        ).start()

    def _prepare_simulation(self):
        """Give simulated symbols tokens and seed synthetic history."""

        with SessionLocal() as db:
            entries = db.query(WatchlistSymbol).all()
            for entry in entries:
                if not entry.token:
                    entry.token = f"SIM-{entry.symbol.split('-')[0]}"
                    entry.token_status = "OK"
                watchlist_service.ensure_paper_account(
                    entry.symbol, entry.initial_capital
                )
            db.commit()

        self._seed_simulated_history()

    def _seed_simulated_history(self):
        """Create a few days of synthetic candles so indicators warm up."""

        with SessionLocal() as db:
            entries = db.query(WatchlistSymbol).filter(
                WatchlistSymbol.enabled == 1
            ).all()

        for entry in entries:
            self._seed_simulated_history_for_symbol(entry.symbol, entry.interval)

    def _seed_simulated_history_for_symbol(self, symbol: str, interval: str = "5min"):
        """Seed synthetic candles for a single symbol if none exist."""
        with SessionLocal() as db:
            has_candles = (
                db.query(Candle)
                .filter(
                    Candle.symbol == symbol,
                    Candle.interval == interval,
                )
                .first()
            )
        if has_candles:
            return

        price = SimulatedFeed.get_anchor_price(symbol)
        now_bucket = datetime.now(timezone.utc).replace(
            second=0, microsecond=0
        )
        start = now_bucket - timedelta(days=SIMULATED_HISTORY_DAYS)
        start = start.replace(minute=(start.minute // 5) * 5)

        records = []
        bucket = start
        while bucket < now_bucket:
            drift = random.gauss(0, 1) * price * 0.0012
            o = price
            c = max(1.0, o + drift)
            h = max(o, c) + abs(random.gauss(0, 1)) * price * 0.0006
            l = min(o, c) - abs(random.gauss(0, 1)) * price * 0.0006
            records.append(
                Candle(
                    symbol=symbol,
                    interval=interval,
                    candle_start=bucket.replace(tzinfo=None),
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(l, 2),
                    close=round(c, 2),
                    tick_count=25,
                    volume=100000,
                )
            )
            price = c
            bucket += timedelta(minutes=5)

        with SessionLocal() as db:
            db.add_all(records)
            db.commit()

        log_event(
            "INFO", "simulation",
            f"Seeded {len(records)} synthetic candles for {symbol}",
        )

    def ensure_symbol_registered(self, symbol: str, token: str | None = None):
        """Ensure a symbol is tracked by the active collector and seeded if in simulation."""
        if not token:
            token = f"SIM-{symbol.split('-')[0]}"
        if self.collector:
            if hasattr(self.collector, "add_symbol"):
                self.collector.add_symbol(symbol, token)
            else:
                self.collector.symbols[symbol] = token
        if self.simulate:
            self._seed_simulated_history_for_symbol(symbol)

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------
    def _builder_loop(self):
        while not self._stop.is_set():
            try:
                build_all_candles()
            except Exception as error:  # noqa: BLE001
                log_event("ERROR", "builder", f"Build cycle failed: {error}")
            self._stop.wait(BUILDER_LOOP_SECONDS)

    def _strategy_loop(self):
        while not self._stop.is_set():
            try:
                results = evaluate_all()
                # Keep the newest *meaningful* result per symbol: a
                # duplicate/no-data cycle must not erase the last signal.
                for symbol, result in results.items():
                    trivial = result.get("status") in ("DUPLICATE", "NO_DATA")
                    if trivial:
                        previous = self.last_results.get(symbol)
                        if previous and previous.get("status") not in (
                            "DUPLICATE",
                            "NO_DATA",
                        ):
                            continue
                    self.last_results[symbol] = result
                refresh_position_prices()
            except Exception as error:  # noqa: BLE001
                log_event("ERROR", "paper",
                          f"Evaluation cycle failed: {error}")
            self._stop.wait(STRATEGY_LOOP_SECONDS)

    def _collector_watchdog(self):
        """Restart the collector if its thread dies unexpectedly."""
        while not self._stop.is_set():
            collector = self.collector
            if (
                collector
                and collector.thread
                and not collector.thread.is_alive()
                and not self._stop.is_set()
            ):
                log_event(
                    "WARN", "engine",
                    "Collector thread died - restarting",
                )
                collector.stop()
                collector.start()
            self._stop.wait(COLLECTOR_RESTART_SECONDS)

    # ------------------------------------------------------------------
    # Status (consumed by the API + dashboard)
    # ------------------------------------------------------------------
    def status(self) -> dict:
        uptime = (
            round(time.time() - self.started_at, 1)
            if self.started_at
            else 0
        )

        collector_status = {
            "type": self.collector.name if self.collector else "none",
            "connected": bool(self.collector and self.collector.connected),
            "symbols": list(self.collector.symbols.keys())
            if self.collector
            else [],
            "ticks_received": self.collector.ticks_received
            if self.collector
            else 0,
            "ticks_written": self.tick_writer.ticks_written,
        }

        with SessionLocal() as db:
            entries = db.query(WatchlistSymbol).all()

            symbols = []
            for entry in entries:
                last_candle = (
                    db.query(Candle)
                    .filter(
                        Candle.symbol == entry.symbol,
                        Candle.interval == entry.interval,
                    )
                    .order_by(Candle.candle_start.desc())
                    .first()
                )
                last_tick = (
                    db.query(MarketTick)
                    .filter(MarketTick.symbol == entry.symbol)
                    .order_by(MarketTick.received_at.desc())
                    .first()
                )

                account = (
                    db.query(PaperAccount)
                    .filter(PaperAccount.symbol == entry.symbol)
                    .first()
                )
                position = (
                    db.query(PaperPosition)
                    .filter(PaperPosition.symbol == entry.symbol)
                    .first()
                )
                result = self.last_results.get(entry.symbol, {})

                candle_age = None
                if last_candle:
                    candle_age = round(
                        (
                            datetime.now(timezone.utc).replace(tzinfo=None)
                            - last_candle.candle_start
                        ).total_seconds()
                        / 60,
                        1,
                    )

                symbols.append(
                    {
                        "symbol": entry.symbol,
                        "exchange": entry.exchange,
                        "interval": entry.interval,
                        "token": entry.token,
                        "token_status": entry.token_status,
                        "enabled": bool(entry.enabled),
                        "last_price": last_tick.ltp if last_tick else None,
                        "last_tick_at": str(last_tick.received_at)
                        if last_tick
                        else None,
                        "last_candle_start": str(last_candle.candle_start)
                        if last_candle
                        else None,
                        "last_candle_age_min": candle_age,
                        "candle_count": last_candle.tick_count
                        if last_candle
                        else 0,
                        "account": {
                            "initial_capital": account.initial_capital
                            if account
                            else entry.initial_capital,
                            "cash": account.cash if account else None,
                            "realized_pnl": account.realized_pnl
                            if account
                            else 0.0,
                        },
                        "position": {
                            "quantity": position.quantity
                            if position
                            else 0,
                            "average_price": position.average_price
                            if position
                            else None,
                            "last_price": position.last_price
                            if position
                            else None,
                            "unrealized_pnl": position.unrealized_pnl
                            if position
                            else 0.0,
                        }
                        if position and position.quantity > 0
                        else None,
                        "last_signal": result.get("signal"),
                        "last_evaluation": result.get("status"),
                        "last_evaluation_reason": result.get("reason"),
                    }
                )

        return {
            "mode": self.mode,
            "running": self.started_at is not None,
            "uptime_seconds": uptime,
            "collector": collector_status,
            "symbols": symbols,
        }


# ----------------------------------------------------------------------
# Process-wide singleton so the CLI and the API share one engine
# ----------------------------------------------------------------------
_ENGINE: TradingEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> TradingEngine | None:
    with _ENGINE_LOCK:
        return _ENGINE


def start_engine(simulate: bool = False) -> TradingEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        _ENGINE = TradingEngine(simulate=simulate)
        _ENGINE.start()
        return _ENGINE


def stop_engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            _ENGINE.stop()
            _ENGINE = None
