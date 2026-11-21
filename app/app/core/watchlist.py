"""Watchlist management: add/remove symbols, resolve tokens dynamically.

The watchlist is DB-backed so it can be edited both from the CLI and
from the web dashboard. Adding a symbol triggers dynamic token
resolution against the downloaded scrip master; when the master file
is missing the symbol stays ``UNRESOLVED`` and is resolved again on the
next engine start.
"""

from app.core.config import DEFAULT_INITIAL_CAPITAL, DEFAULT_MAX_POSITION_PCT, DEFAULT_MAX_POSITION_VALUE
from app.core.database import SessionLocal
from app.core.events import log_event
from app.core.models import PaperAccount, WatchlistSymbol

DEFAULT_WATCHLIST = [
    {"symbol": "SBIN-EQ", "initial_capital": 100000.0},
    {"symbol": "KROSS-EQ", "initial_capital": 100000.0},
]


def seed_default_watchlist():
    """Create the default watchlist and per-symbol paper accounts."""

    with SessionLocal() as db:
        for entry in DEFAULT_WATCHLIST:
            exists = (
                db.query(WatchlistSymbol)
                .filter(
                    WatchlistSymbol.symbol == entry["symbol"],
                    WatchlistSymbol.exchange == "NSE",
                )
                .first()
            )
            if exists:
                continue

            db.add(
                WatchlistSymbol(
                    symbol=entry["symbol"],
                    exchange="NSE",
                    interval="5min",
                    enabled=1,
                    initial_capital=entry["initial_capital"],
                    max_position_value=DEFAULT_MAX_POSITION_VALUE,
                    max_position_pct=DEFAULT_MAX_POSITION_PCT,
                )
            )

        db.commit()

    log_event("INFO", "watchlist", "Default watchlist seeded")


def add_symbol(
    symbol: str,
    interval: str = "5min",
    exchange: str = "NSE",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    max_position_value: float = DEFAULT_MAX_POSITION_VALUE,
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
    resolver=None,
) -> WatchlistSymbol:
    """Add a symbol to the watchlist and resolve its token dynamically."""

    with SessionLocal() as db:
        existing = (
            db.query(WatchlistSymbol)
            .filter(
                WatchlistSymbol.symbol == symbol.upper(),
                WatchlistSymbol.exchange == exchange,
                WatchlistSymbol.interval == interval,
            )
            .first()
        )
        if existing:
            raise ValueError(f"{symbol} already exists in the watchlist")

        token = None
        token_status = "UNRESOLVED"

        if resolver is not None:
            try:
                token = resolver.resolve_token(symbol, exchange)
                token_status = "OK" if token else "UNRESOLVED"
            except Exception as error:  # noqa: BLE001
                token_status = f"ERROR: {error}"

        entry = WatchlistSymbol(
            symbol=symbol.upper(),
            exchange=exchange,
            interval=interval,
            token=token,
            token_status=token_status,
            enabled=1,
            initial_capital=initial_capital,
            max_position_value=max_position_value,
            max_position_pct=max_position_pct,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        ensure_paper_account(entry.symbol, initial_capital)

        log_event(
            "INFO", "watchlist",
            f"Added {entry.symbol} (token={token or 'unresolved'})",
        )
        return entry


def remove_symbol(symbol: str, interval: str = "5min") -> bool:
    with SessionLocal() as db:
        entry = (
            db.query(WatchlistSymbol)
            .filter(
                WatchlistSymbol.symbol == symbol.upper(),
                WatchlistSymbol.interval == interval,
            )
            .first()
        )
        if not entry:
            return False
        db.delete(entry)
        db.commit()

    log_event("WARN", "watchlist", f"Removed {symbol.upper()} from watchlist")
    return True


def set_enabled(symbol: str, enabled: bool, interval: str = "5min") -> bool:
    with SessionLocal() as db:
        entry = (
            db.query(WatchlistSymbol)
            .filter(
                WatchlistSymbol.symbol == symbol.upper(),
                WatchlistSymbol.interval == interval,
            )
            .first()
        )
        if not entry:
            return False
        entry.enabled = 1 if enabled else 0
        db.commit()
    return True


def ensure_paper_account(symbol: str, initial_capital: float) -> PaperAccount:
    """Create the per-symbol paper account if it does not exist yet."""

    with SessionLocal() as db:
        account = (
            db.query(PaperAccount)
            .filter(PaperAccount.symbol == symbol)
            .first()
        )
        if account is None:
            account = PaperAccount(
                symbol=symbol,
                initial_capital=initial_capital,
                cash=initial_capital,
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            log_event(
                "INFO", "paper",
                f"Opened paper account for {symbol} "
                f"with Rs.{initial_capital:,.0f}",
            )
        return account


def resolve_watchlist_tokens(resolver, only_unresolved: bool = True) -> dict:
    """Resolve tokens for watchlist symbols (all or only unresolved)."""

    with SessionLocal() as db:
        query = db.query(WatchlistSymbol)
        if only_unresolved:
            query = query.filter(WatchlistSymbol.token_status != "OK")
        entries = query.all()

        results = {}
        for entry in entries:
            token = resolver.resolve_token(entry.symbol, entry.exchange)
            if token:
                entry.token = token
                entry.token_status = "OK"
            elif entry.token_status == "OK":
                # Keep the previous token; mark for later re-check.
                entry.token_status = "RETRY"
            results[entry.symbol] = token
        db.commit()

    unresolved = [s for s, t in results.items() if not t]
    if unresolved:
        log_event(
            "WARN", "watchlist",
            f"Unresolved tokens: {', '.join(unresolved)}",
        )

    return results
