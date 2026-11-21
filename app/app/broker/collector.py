"""One generic market-data collector for every watchlist symbol.

Two feed implementations share the same interface:

* ``LiveMarketDataCollector`` - a single Angel One SmartWebSocketV2
  connection subscribed to every enabled symbol's token.
* ``SimulatedFeed`` - a synthetic random-walk feed used when Angel One
  credentials are unavailable (or for offline testing / demos).

Both push ticks through a shared batching writer that persists
``MarketTick`` rows in bulk.
"""

from __future__ import annotations

import os
import queue
import random
import threading
import time
from datetime import datetime, timezone

from app.core.config import (
    TICK_FLUSH_BATCH,
    TICK_FLUSH_SECONDS,
    WEBSOCKET_RETRY_MAX,
)
from app.core.database import SessionLocal
from app.core.events import log_event
from app.core.models import MarketTick

EXCHANGE_TYPE_NSE = 1
SUBSCRIPTION_MODE_LTP = 1


# ----------------------------------------------------------------------
# Tick batch writer (shared by live + simulated feeds)
# ----------------------------------------------------------------------
class TickWriter:
    """Queue-backed batch writer for MarketTick rows."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ticks_written = 0
        self.last_write_at: float | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tick-writer", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def submit(self, item: dict):
        self._queue.put(item)

    def _run(self):
        batch = []
        last_flush = time.monotonic()

        while not self._stop.is_set() or not self._queue.empty():
            try:
                batch.append(self._queue.get(timeout=0.5))
                self._queue.task_done()
            except queue.Empty:
                pass

            due = (
                len(batch) >= TICK_FLUSH_BATCH
                or (batch and time.monotonic() - last_flush >= TICK_FLUSH_SECONDS)
                or (batch and self._stop.is_set() and self._queue.empty())
            )

            if due and batch:
                try:
                    with SessionLocal() as db:
                        db.add_all([MarketTick(**item) for item in batch])
                        db.commit()
                    self.ticks_written += len(batch)
                    self.last_write_at = time.monotonic()
                except Exception as error:  # noqa: BLE001
                    log_event("ERROR", "collector", f"Tick write failed: {error}")
                batch.clear()
                last_flush = time.monotonic()


# ----------------------------------------------------------------------
# Base class
# ----------------------------------------------------------------------
class BaseCollector:
    """Common collector interface used by the engine runner."""

    name = "base"

    def __init__(self, symbols: dict[str, str], tick_writer: TickWriter):
        """``symbols`` maps symbol -> token."""
        self.symbols = symbols
        self.writer = tick_writer
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.connected = False
        self.started_at: float | None = None
        self.ticks_received = 0
        self.last_tick_at: float | None = None

    def start(self):
        self.stop_event.clear()
        self.started_at = time.monotonic()
        self.thread = threading.Thread(
            target=self._run_guarded, name=f"collector-{self.name}", daemon=True
        )
        self.thread.start()

    def _run_guarded(self):
        try:
            self._run()
        except Exception as error:  # noqa: BLE001
            log_event("ERROR", "collector", f"{self.name} crashed: {error}")

    def _run(self):  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def submit_tick(self, symbol: str, token: str, ltp: float):
        received_time = datetime.now(timezone.utc)
        self.writer.submit(
            {
                "symbol": symbol,
                "token": token,
                "exchange": "NSE",
                "ltp": ltp,
                "exchange_timestamp": received_time.isoformat(),
                "received_at": received_time.replace(tzinfo=None),
            }
        )
        self.ticks_received += 1
        self.last_tick_at = time.monotonic()


# ----------------------------------------------------------------------
# Live Angel One WebSocket collector
# ----------------------------------------------------------------------
class LiveMarketDataCollector(BaseCollector):
    name = "live"

    def _run(self):
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        from app.broker.angel_one import connect_angel_one

        token_groups = [
            {
                "exchangeType": EXCHANGE_TYPE_NSE,
                "tokens": list(self.symbols.values()),
            }
        ]

        while not self.stop_event.is_set():
            attempt = 0
            try:
                log_event(
                    "INFO", "collector",
                    f"Authenticating with Angel One "
                    f"({len(self.symbols)} symbols)",
                )
                session = connect_angel_one()

                ws = SmartWebSocketV2(
                    session["jwt_token"],
                    os.getenv("ANGEL_API_KEY"),
                    session["client_code"],
                    session["feed_token"],
                    max_retry_attempt=0,
                )

                token_to_symbol = {
                    token: symbol for symbol, token in self.symbols.items()
                }

                def on_open(wsapp):
                    self.connected = True
                    log_event(
                        "INFO", "collector",
                        "WebSocket connected; subscribing to "
                        f"{len(token_groups[0]['tokens'])} tokens",
                    )
                    ws.subscribe(
                        "algo_collector01",
                        SUBSCRIPTION_MODE_LTP,
                        token_groups,
                    )

                def on_data(wsapp, message):
                    raw_price = message.get("last_traded_price")
                    token = str(message.get("token", ""))
                    if raw_price is None or token not in token_to_symbol:
                        return
                    try:
                        ltp = float(raw_price) / 100
                    except (TypeError, ValueError):
                        return
                    self.submit_tick(token_to_symbol[token], token, ltp)

                def on_error(wsapp, error):
                    self.connected = False
                    log_event("WARN", "collector", f"WebSocket error: {error}")

                def on_close(wsapp):
                    self.connected = False
                    log_event("WARN", "collector", "WebSocket closed")

                ws.on_open = on_open
                ws.on_data = on_data
                ws.on_error = on_error
                ws.on_close = on_close

                ws.connect()

            except Exception as error:  # noqa: BLE001
                self.connected = False
                attempt += 1
                if attempt > WEBSOCKET_RETRY_MAX:
                    log_event(
                        "ERROR", "collector",
                        f"Giving up after {WEBSOCKET_RETRY_MAX} retries: {error}",
                    )
                    break
                delay = min(60, 2 ** attempt)
                log_event(
                    "WARN", "collector",
                    f"Collector reconnect in {delay}s "
                    f"(attempt {attempt}): {error}",
                )
                time.sleep(delay)


# ----------------------------------------------------------------------
# Simulated feed (no broker credentials required)
# ----------------------------------------------------------------------
class SimulatedFeed(BaseCollector):
    """Synthetic random-walk ticks for every configured symbol."""

    name = "simulated"

    # Stable per-symbol price anchors so each stock behaves differently.
    _ANCHORS = {
        "SBIN-EQ": 820.0,
        "SBIN": 820.0,
        "KROSS-EQ": 252.0,
        "KROSS": 252.0,
        "TCS-EQ": 4150.0,
        "TCS": 4150.0,
        "RELIANCE-EQ": 2980.0,
        "RELIANCE": 2980.0,
        "INFY-EQ": 1890.0,
        "INFY": 1890.0,
        "HDFCBANK-EQ": 1680.0,
        "HDFCBANK": 1680.0,
        "TATAMOTORS-EQ": 980.0,
        "TATAMOTORS": 980.0,
        "ICICIBANK-EQ": 1250.0,
        "ICICIBANK": 1250.0,
        "WIPRO-EQ": 560.0,
        "WIPRO": 560.0,
        "LT-EQ": 3620.0,
        "LT": 3620.0,
        "ITC-EQ": 475.0,
        "ITC": 475.0,
        "BHARTIARTL-EQ": 1580.0,
        "BHARTIARTL": 1580.0,
    }
    _DEFAULT_ANCHOR = 500.0

    @classmethod
    def get_anchor_price(cls, symbol: str) -> float:
        norm = symbol.upper().strip()
        bare = norm.split("-")[0]
        if norm in cls._ANCHORS:
            return cls._ANCHORS[norm]
        if bare in cls._ANCHORS:
            return cls._ANCHORS[bare]
        for key, value in cls._ANCHORS.items():
            if bare == key.split("-")[0]:
                return value
        return cls._DEFAULT_ANCHOR + (hash(symbol) % 400)

    def __init__(self, symbols: dict[str, str], tick_writer: TickWriter,
                 ticks_per_second: float = 2.0):
        super().__init__(symbols, tick_writer)
        self.interval = 1.0 / max(ticks_per_second, 0.1)
        self._prices: dict[str, float] = {}

    def add_symbol(self, symbol: str, token: str, initial_price: float | None = None):
        self.symbols[symbol] = token
        if initial_price:
            self._prices[symbol] = initial_price

    def _anchor(self, symbol: str) -> float:
        return self.get_anchor_price(symbol)

    def _run(self):
        self.connected = True
        log_event(
            "INFO", "collector",
            f"Simulated feed started for {len(self.symbols)} symbols",
        )

        while not self.stop_event.is_set():
            for symbol, token in list(self.symbols.items()):
                price = self._prices.get(symbol)
                if price is None:
                    price = self._anchor(symbol)
                drift = random.gauss(0, 1) * price * 0.0008
                price = max(1.0, price + drift)
                self._prices[symbol] = price
                self.submit_tick(symbol, token, round(price, 2))
            time.sleep(self.interval)

        self.connected = False
