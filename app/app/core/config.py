"""Central configuration for the algo-trading application.

Everything path- or environment-related lives here so that every
module shares a single source of truth.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------
# app/core/config.py -> parents[2] is the project root that holds
# the `app` package (run every command from the project root).
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
WEB_BUILD_DIR = BASE_DIR / "dist"

for directory in (DATA_DIR, CONFIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------
# Database
# ---------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'algo_trading.db'}",
)

# ---------------------------------------------------------------
# Angel One broker
# ---------------------------------------------------------------
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)
SCRIP_MASTER_FILE = DATA_DIR / "OpenAPIScripMaster.json"

ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "")
ANGEL_PIN = os.getenv("ANGEL_PIN", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")


def angel_credentials_configured() -> bool:
    """True when every credential required for live mode is present."""
    return all(
        [ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET]
    )


# ---------------------------------------------------------------
# Trading / risk defaults
# ---------------------------------------------------------------
DEFAULT_EXCHANGE = "NSE"
DEFAULT_INTERVAL = "5min"

# Candle intervals built from ticks (label -> pandas resample rule).
INTERVALS = {
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "1hour": "1h",
}

# Angel One historical API interval mapping.
HISTORICAL_INTERVAL = {
    "1min": "ONE_MINUTE",
    "5min": "FIVE_MINUTE",
    "15min": "FIFTEEN_MINUTE",
    "1hour": "ONE_HOUR",
}

# Strategy
STRATEGY_NAME = "EMA20_EMA50_RSI14_MACD"

# Risk limits (application-level defaults; per-symbol overrides are
# stored on the watchlist row).
DEFAULT_INITIAL_CAPITAL = 100000.0
DEFAULT_MAX_POSITION_VALUE = 20000.0
DEFAULT_MAX_POSITION_PCT = 0.20        # max fraction of cash per position
GLOBAL_MAX_OPEN_POSITIONS = 5            # across all symbols
MIN_CANDLES_FOR_SIGNAL = 60              # indicator warm-up requirement

# Maximum permitted age of the newest completed candle before the
# paper engine refuses to trade on it (stale-data protection).
MAX_CANDLE_AGE_MINUTES = 10

# ---------------------------------------------------------------
# Engine loop tuning
# ---------------------------------------------------------------
BUILDER_LOOP_SECONDS = 10        # candle build cycle
STRATEGY_LOOP_SECONDS = 10     # strategy evaluation cycle
COLLECTOR_RESTART_SECONDS = 5    # delay before restarting a dead collector
TICK_FLUSH_SECONDS = 1.0         # tick batch flush interval
TICK_FLUSH_BATCH = 50            # tick batch size before forced flush
WEBSOCKET_RETRY_MAX = 10         # reconnect attempts (exponential backoff)
