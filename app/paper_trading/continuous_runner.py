
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from app.core.database import BASE_DIR


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "data" / "algo_trading.db"

SYMBOL = "KROSS-EQ"
INTERVAL = "5min"

POLL_SECONDS = 15
RESTART_DELAY_SECONDS = 5
MAX_COLLECTOR_RETRIES = 5           # Max consecutive failures before halting collector restarts
BASE_RESTART_DELAY_SECONDS = 5     # Base backoff delay
MAX_RESTART_DELAY_SECONDS = 60     # Cap on exponential backoff
STABLE_RUN_SECONDS = 60            # Seconds of stable running to reset failure counter

COLLECTOR_MODULE = "app.broker.collect_market_data"
CANDLE_MODULE = "app.backtesting.candle_builder"
PAPER_MODULE = "app.paper_trading.paper_engine"


# --------------------------------------------------
# TIMESTAMP NORMALIZATION
# --------------------------------------------------

def normalize_candle_key(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value))
        return dt.replace(tzinfo=None).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return str(value)


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_latest_candle_key():

    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(DB_PATH, timeout=30)

    try:
        row = conn.execute("""
            SELECT candle_start
            FROM candles
            WHERE symbol = ?
              AND interval = ?
            ORDER BY candle_start DESC
            LIMIT 1
        """, (SYMBOL, INTERVAL)).fetchone()

        return normalize_candle_key(row[0]) if row else None

    except sqlite3.OperationalError as error:
        print("[RUNNER] Candle database check:", error)
        return None

    finally:
        conn.close()


def get_last_processed_candle_key():

    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(DB_PATH, timeout=30)

    try:
        row = conn.execute("""
            SELECT candle_start
            FROM paper_processed_candles
            WHERE symbol = ?
              AND interval = ?
            ORDER BY candle_start DESC
            LIMIT 1
        """, (SYMBOL, INTERVAL)).fetchone()

        return normalize_candle_key(row[0]) if row else None

    except sqlite3.OperationalError as error:
        print("[RUNNER] Processed-candle database check:", error)
        return None

    finally:
        conn.close()


# --------------------------------------------------
# SUBPROCESS HELPERS
# --------------------------------------------------

def run_module(module_name):

    print(f"\n[RUNNER] Running {module_name}")

    result = subprocess.run(
        [sys.executable, "-u", "-m", module_name],
        cwd=str(PROJECT_ROOT),
        check=False
    )

    if result.returncode != 0:
        print(
            f"[RUNNER] {module_name} exited "
            f"with code {result.returncode}"
        )

    return result.returncode


def start_collector():

    print("\n[RUNNER] Starting market-data collector...")

    return subprocess.Popen(
        [sys.executable, "-u", "-m", COLLECTOR_MODULE],
        cwd=str(PROJECT_ROOT)
    )


def stop_collector(process):

    if process is None or process.poll() is not None:
        return

    print("\n[RUNNER] Stopping market-data collector...")

    process.terminate()

    try:
        process.wait(timeout=15)

    except subprocess.TimeoutExpired:
        print("[RUNNER] Collector did not stop. Killing process...")
        process.kill()
        process.wait(timeout=5)


# --------------------------------------------------
# CONTINUOUS RUNNER
# --------------------------------------------------

def main():
    import signal

    shutdown_requested = False

    def handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        print(f"\n[RUNNER] Received signal {signum}. Initiating graceful shutdown...")
        shutdown_requested = True

    # Handle both Ctrl+C (SIGINT) and systemd stop (SIGTERM)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    collector = None
    collector_started_at = None
    consecutive_failures = 0
    collector_halted = False

    # Restore last processed candle from SQLite
    last_processed_candle = get_last_processed_candle_key()

    print("=" * 55)
    print("KROSS CONTINUOUS PAPER TRADING RUNNER")
    print("=" * 55)
    print(f"Symbol: {SYMBOL}")
    print(f"Interval: {INTERVAL}")
    print(f"Polling interval: {POLL_SECONDS} seconds")
    print(f"Last processed candle: {last_processed_candle}")
    print("Real order execution: DISABLED")
    print("=" * 55)

    try:
        while not shutdown_requested:
            # Start or restart collector with controlled retry policy & circuit breaker
            if not collector_halted:
                if collector is None or collector.poll() is not None:
                    if collector is not None:
                        exit_code = collector.returncode
                        uptime = (
                            time.monotonic() - collector_started_at
                            if collector_started_at
                            else 0
                        )
                        print(
                            f"[RUNNER] Collector exited (code: {exit_code}, uptime: {uptime:.1f}s)"
                        )

                        if exit_code == 75:
                            collector_halted = True
                            print(
                                "\n[RUNNER] Collector aborted: another Angel One WebSocket process holds the lock."
                            )
                            print(
                                "[RUNNER] Halting collector restarts to prevent broker connection limit (HTTP 429) conflict."
                            )
                            continue

                        # If collector ran stably, reset consecutive failures
                        if uptime >= STABLE_RUN_SECONDS:
                            consecutive_failures = 0

                        consecutive_failures += 1

                        if consecutive_failures >= MAX_COLLECTOR_RETRIES:
                            collector_halted = True
                            print(
                                f"\n[RUNNER] CIRCUIT BREAKER TRIPPED: Collector failed "
                                f"{consecutive_failures} consecutive times."
                            )
                            print(
                                "[RUNNER] Halting collector restarts to prevent broker "
                                "connection limit (HTTP 429) exhaustion."
                            )
                            print(
                                "[RUNNER] Manual investigation required. Check logs and credentials."
                            )
                        else:
                            # Capped exponential backoff: 5s, 10s, 20s, 40s, 60s
                            backoff_delay = min(
                                MAX_RESTART_DELAY_SECONDS,
                                BASE_RESTART_DELAY_SECONDS * (2 ** (consecutive_failures - 1)),
                            )
                            print(
                                f"[RUNNER] Waiting {backoff_delay}s before restart attempt "
                                f"{consecutive_failures + 1}/{MAX_COLLECTOR_RETRIES}..."
                            )
                            for _ in range(int(backoff_delay)):
                                if shutdown_requested:
                                    break
                                time.sleep(1)

                    if not collector_halted and not shutdown_requested:
                        collector = start_collector()
                        collector_started_at = time.monotonic()

            if shutdown_requested:
                break

            # Generate completed candles
            builder_status = run_module(CANDLE_MODULE)

            if builder_status == 0:
                latest_key = get_latest_candle_key()

                if latest_key and latest_key != last_processed_candle:
                    print(
                        "\n[RUNNER] New completed candle detected:",
                        latest_key
                    )

                    paper_status = run_module(PAPER_MODULE)

                    if paper_status == 0:
                        # Read the actual database record.
                        # The paper engine may reject a duplicate candle.
                        last_processed_candle = (
                            get_last_processed_candle_key()
                        )
                else:
                    print(
                        "[RUNNER] No new completed 5-minute candle."
                    )
            else:
                print(
                    "[RUNNER] Candle builder failed. "
                    "Paper engine will not run this cycle."
                )

            print(
                f"\n[RUNNER] Next check in {POLL_SECONDS} seconds..."
            )

            # Interruptible poll sleep
            for _ in range(POLL_SECONDS):
                if shutdown_requested:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[RUNNER] Shutdown requested.")

    finally:
        stop_collector(collector)
        print("[RUNNER] Continuous paper trading stopped.")
        print("[RUNNER] Real order execution was never enabled.")


if __name__ == "__main__":
    main()
