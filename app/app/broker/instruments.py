"""NSE symbol <-> token resolution backed by the Angel One scrip master.

The scrip master file (OpenAPIScripMaster.json) is downloaded once and
cached under ``data/``; symbols are resolved against it dynamically, so
adding a new stock to the watchlist never requires a code change.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from app.core.config import SCRIP_MASTER_FILE, SCRIP_MASTER_URL
from app.core.events import log_event

DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_BACKOFF_SECONDS = 3

# Instrument types used by Angel One for the NSE cash market.
CASH_INSTRUMENT_TYPES = {"EQ"}


def download_scrip_master(
    output_file: Path = SCRIP_MASTER_FILE,
    force: bool = False,
) -> Path:
    """Download the scrip master JSON (retries with backoff)."""

    if output_file.exists() and not force:
        return output_file

    output_file.parent.mkdir(parents=True, exist_ok=True)

    last_error = None

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            response = requests.get(SCRIP_MASTER_URL, timeout=60)
            response.raise_for_status()

            records = response.json()
            if not isinstance(records, list) or not records:
                raise ValueError("Scrip master response was empty")

            output_file.write_text(json.dumps(records))
            log_event(
                "INFO",
                "instruments",
                f"Scrip master downloaded ({len(records)} instruments)",
            )
            return output_file

        except Exception as error:  # noqa: BLE001 - retried below
            last_error = error
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(DOWNLOAD_BACKOFF_SECONDS)

    raise RuntimeError(
        f"Could not download scrip master after {DOWNLOAD_ATTEMPTS} "
        f"attempts: {last_error}"
    )


class InstrumentResolver:
    """Resolve NSE trading symbols to broker tokens using the master file.

    The index maps both ``"SBIN-EQ"`` style symbols and bare names like
    ``"SBIN"`` (plus ``"NSE:SBIN"``) to their instrument record. When a
    symbol is not found the master file is refreshed once before giving up.
    """

    def __init__(self, master_file: Path = SCRIP_MASTER_FILE):
        self.master_file = Path(master_file)
        self._index: dict[str, dict] = {}
        self._loaded_at: float | None = None
        self.load()

    def load(self):
        if not self.master_file.exists():
            raise FileNotFoundError(
                f"Scrip master not found at {self.master_file}. "
                "Run: python3 -m app.main instruments"
            )

        records = json.loads(self.master_file.read_text())

        self._index = {}
        for record in records:
            if record.get("exch_seg") != "NSE":
                continue
            instrument_type = str(record.get("instrumenttype") or "").strip().upper()
            record_symbol = str(record.get("symbol") or "").strip().upper()

            if instrument_type not in CASH_INSTRUMENT_TYPES and not (
                not instrument_type and record_symbol.endswith("-EQ")
            ):
                continue

            token = str(record.get("token", ""))
            symbol = str(record.get("symbol", ""))
            name = str(record.get("name", ""))

            if not token or not symbol:
                continue

            # Primary key: full trading symbol (SBIN-EQ).
            self._index.setdefault(symbol.upper(), record)
            # Bare name without the -EQ suffix.
            if name:
                self._index.setdefault(name.upper(), record)

        self._loaded_at = time.time()

    @property
    def size(self) -> int:
        return len(self._index)

    def resolve(self, symbol: str, exchange: str = "NSE") -> dict | None:
        """Return the instrument record for a symbol, or None."""

        if exchange != "NSE":
            return None

        key = symbol.upper()

        record = self._index.get(key)
        if record is not None:
            return record

        # One automatic refresh before declaring the symbol unknown --
        # the master file changes daily and symbols migrate.
        self.load()
        return self._index.get(key)

    def resolve_token(self, symbol: str, exchange: str = "NSE") -> str | None:
        record = self.resolve(symbol, exchange)
        return str(record["token"]) if record else None

    def resolve_many(
        self,
        symbols: list[str],
        exchange: str = "NSE",
    ) -> dict[str, str | None]:
        """Resolve several symbols at once -> {symbol: token | None}."""
        return {
            symbol: self.resolve_token(symbol, exchange)
            for symbol in symbols
        }
