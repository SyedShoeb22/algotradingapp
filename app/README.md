# NSE Paper Trading Desk

A unified, single-entry-point algo-trading automation system for NSE stocks
(Angel One SmartAPI). It replaces the old per-stock scripts (separate
KROSS/SBI collectors, candle builders, paper engines and runners) with one
generic engine that handles every symbol in the watchlist.

**Real order execution is never performed — all trades are paper trades.**

## What it does

- **Dynamic NSE symbol/token resolution** — symbols are mapped to broker
  tokens automatically from the Angel One scrip master file. Adding a new
  stock needs no code changes and no hardcoded token.
- **Automatic historical candle import** — on startup the engine back-fills
  each enabled symbol with recent candles so indicators warm up immediately.
- **One generic WebSocket collector and candle builder** — a single
  SmartWebSocket V2 connection subscribes to every watchlist token; ticks are
  batched to SQLite and resampled into 1m/5m/15m/1h OHLC candles for all
  symbols. A built-in **simulated feed** (`--simulate`) runs the entire
  pipeline without broker credentials.
- **Separate paper capital per stock** — each symbol gets its own account,
  cash balance, position and P&L.
- **Automatic strategy evaluation and continuous paper trading** — EMA 20/50
  + RSI 14 + MACD signals are evaluated on every completed candle, in threads,
  with no subprocess orchestration.
- **Duplicate-candle protection** (database-enforced claim per candle),
  **stale-data checks** (candles older than 10 minutes are never traded on)
  and **risk limits** (per-stock position value/% caps, global open-position
  cap, cash checks).
- **One CLI entry point** — everything is driven by `python3 -m app.main`.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in for LIVE mode (optional)

python3 -m app.main dashboard --simulate
# open http://127.0.0.1:8000
```

The dashboard shows engine status, watchlist, per-stock paper accounts,
trades, live charts with signals, backtests and settings. The same server
hosts the REST API (`/api/...`) consumed by the dashboard.

## CLI

| Command | Purpose |
|---|---|
| `python3 -m app.main init-db` | Create/upgrade the SQLite schema |
| `python3 -m app.main instruments` | Download the NSE scrip master (token map) |
| `python3 -m app.main resolve` | Resolve watchlist symbols to tokens |
| `python3 -m app.main import-history [-s SYMBOL] [-d DAYS]` | Back-fill historical candles |
| `python3 -m app.main backtest -s SYMBOL [-d DAYS] [-c CAPITAL]` | Walk-forward backtest on stored candles |
| `python3 -m app.main run [--simulate]` | Headless engine loop (Ctrl+C to stop) |
| `python3 -m app.main dashboard [--simulate] [--port 8000]` | Engine + REST API + web dashboard |

## Live mode

1. Put your Angel One credentials in `.env` (`ANGEL_API_KEY`,
   `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`).
2. `python3 -m app.main instruments` (downloads the scrip master).
3. `python3 -m app.main dashboard` — token resolution and historical
   import happen automatically at startup.

## Project layout

```
app/
  main.py               # single CLI entry point
  core/                 # config, database, models, watchlist, event log
  broker/               # Angel One auth, scrip master, WebSocket collector, history import
  data/                 # generic tick -> OHLC candle builder (all symbols)
  strategy/             # indicators, signals, walk-forward backtest
  paper/                # paper engine (per-stock capital, dedup, stale checks) + runner
  api/                  # FastAPI REST backend, serves the built dashboard
data/                   # SQLite database + scrip master (created at runtime)
src/                    # React dashboard source (Vite + Tailwind + shadcn/ui)
dist/                   # built dashboard (served by the FastAPI app)
```

## Dashboard

The React dashboard is built with Vite/Tailwind/shadcn and talks to the
engine's REST API. If the API is unreachable (e.g. a static preview), it
falls back to a clearly-labelled demo dataset. It is installable as a PWA.

Rebuild after editing the UI:

```bash
npm install
npm run build
```
