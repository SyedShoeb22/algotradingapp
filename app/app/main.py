"""Single CLI entry point for the whole system.

Usage:
    python3 -m app.main init-db                  create/upgrade tables
    python3 -m app.main instruments [--force]    download NSE scrip master
    python3 -m app.main resolve                  resolve watchlist tokens
    python3 -m app.main import-history [-s SYM]  fetch historical candles
    python3 -m app.main backtest -s SYM          run a walk-forward backtest
    python3 -m app.main run [--simulate]         headless engine loop
    python3 -m app.main dashboard [--simulate]   engine + API + web UI
"""

import argparse
import sys
import time


def cmd_init_db(_args):
    from app.core.database import initialize_database

    initialize_database()
    print("Database initialized.")


def cmd_instruments(args):
    from app.broker.instruments import InstrumentResolver, download_scrip_master

    path = download_scrip_master(force=args.force)
    resolver = InstrumentResolver(path)
    print(f"Scrip master ready: {path}")
    print(f"Indexed NSE cash symbols: {resolver.size}")


def cmd_resolve(_args):
    from app.broker.instruments import InstrumentResolver, download_scrip_master

    from app.core import watchlist as watchlist_service

    download_scrip_master()
    resolver = InstrumentResolver()
    watchlist_service.seed_default_watchlist()
    results = watchlist_service.resolve_watchlist_tokens(
        resolver, only_unresolved=False
    )
    for symbol, token in results.items():
        state = f"token {token}" if token else "UNRESOLVED"
        print(f"  {symbol:<15} {state}")


def cmd_import_history(args):
    from app.broker.angel_one import connect_angel_one
    from app.broker.historical import import_historical_candles
    from app.core import watchlist as watchlist_service

    watchlist_service.seed_default_watchlist()

    session = connect_angel_one()

    symbols = [args.symbol] if args.symbol else None

    from app.core.database import SessionLocal
    from app.core.models import WatchlistSymbol

    with SessionLocal() as db:
        query = db.query(WatchlistSymbol).filter(
            WatchlistSymbol.token.isnot(None)
        )
        if symbols:
            query = query.filter(WatchlistSymbol.symbol.in_(
                [s.upper() for s in symbols]
            ))
        entries = query.all()

    if not entries:
        print("No symbols with resolved tokens. Run: python3 -m app.main resolve")
        return

    for entry in entries:
        count = import_historical_candles(
            session["smart_api"],
            entry.symbol,
            entry.token,
            interval=entry.interval,
            days=args.days,
            exchange=entry.exchange,
        )
        print(f"  {entry.symbol}: {count} candles imported")


def cmd_backtest(args):
    from app.strategy.backtest import run_backtest

    result = run_backtest(
        args.symbol.upper(),
        interval=args.interval,
        days=args.days,
        initial_capital=args.capital,
        max_position_value=args.max_position_value,
        max_position_pct=args.max_position_pct,
    )

    print("=" * 55)
    print(f"BACKTEST  {result.symbol} ({result.interval}, last {args.days}d)")
    print("=" * 55)
    print(f"Initial capital : Rs.{result.initial_capital:,.0f}")
    print(f"Final equity    : Rs.{result.final_equity:,.2f}")
    print(f"Total return    : {result.total_return_pct:+.2f}%")
    print(f"Trades          : {len(result.trades)} "
          f"({result.buy_signals} buys / {result.sell_signals} sells)")
    if result.trades:
        print("\nLast trades:")
        for trade in result.trades[-10:]:
            pnl = f"  P&L Rs.{trade['pnl']:+,.0f}" if "pnl" in trade else ""
            print(
                f"  {trade['time']}  {trade['side']:<4} "
                f"{trade['quantity']:>5} @ {trade['price']:.2f}{pnl}"
            )


def cmd_run(args):
    from app.paper.runner import start_engine

    engine = start_engine(simulate=args.simulate)
    print("=" * 55)
    print(f"ENGINE RUNNING  ({engine.mode} mode)")
    print("Press Ctrl+C to stop. Real order execution: DISABLED")
    print("=" * 55)

    try:
        while True:
            time.sleep(5)
            status = engine.status()
            collector = status["collector"]
            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"collector={'up' if collector['connected'] else 'down'} "
                f"symbols={len(status['symbols'])} "
                f"ticks={collector['ticks_written']}"
            )
    except KeyboardInterrupt:
        print("\nStopping engine...")
    finally:
        from app.paper.runner import stop_engine

        stop_engine()
        print("Engine stopped.")


def cmd_dashboard(args):
    import uvicorn

    from app.core.database import initialize_database
    from app.paper.runner import start_engine

    initialize_database()

    if not args.no_engine:
        engine = start_engine(simulate=args.simulate)
        print(f"Engine started in {engine.mode} mode.")
    else:
        print("Engine not started (--no-engine). Dashboard in read-only mode.")

    print(f"Dashboard: http://{args.host}:{args.port}")
    print("Real order execution: DISABLED")

    uvicorn.run(
        "app.api.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m app.main",
        description="Unified NSE paper-trading automation system",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create/upgrade database tables")

    p = sub.add_parser("instruments", help="Download NSE scrip master")
    p.add_argument("--force", action="store_true",
                   help="Re-download even if cached")

    sub.add_parser("resolve", help="Resolve watchlist symbols to tokens")

    p = sub.add_parser("import-history",
                       help="Import historical candles from Angel One")
    p.add_argument("--symbol", "-s", default=None,
                   help="Only this symbol (default: whole watchlist)")
    p.add_argument("--days", "-d", type=int, default=5,
                   help="How many days of history (max 100 per request)")

    p = sub.add_parser("backtest", help="Walk-forward backtest on stored candles")
    p.add_argument("--symbol", "-s", required=True)
    p.add_argument("--interval", "-i", default="5min")
    p.add_argument("--days", "-d", type=int, default=30)
    p.add_argument("--capital", "-c", type=float, default=100000.0)
    p.add_argument("--max-position-value", type=float, default=20000.0)
    p.add_argument("--max-position-pct", type=float, default=0.20)

    p = sub.add_parser("run", help="Run the engine headless (Ctrl+C to stop)")
    p.add_argument("--simulate", action="store_true",
                   help="Use the built-in simulated market feed")

    p = sub.add_parser("dashboard",
                       help="Run engine + API + web dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", "-p", type=int, default=8000)
    p.add_argument("--simulate", action="store_true",
                   help="Use the built-in simulated market feed")
    p.add_argument("--no-engine", action="store_true",
                   help="Serve the dashboard without starting the engine")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init-db": cmd_init_db,
        "instruments": cmd_instruments,
        "resolve": cmd_resolve,
        "import-history": cmd_import_history,
        "backtest": cmd_backtest,
        "run": cmd_run,
        "dashboard": cmd_dashboard,
    }

    handlers[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
