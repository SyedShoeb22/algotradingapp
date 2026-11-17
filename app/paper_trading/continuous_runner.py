
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

    collector = None

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

        while True:

            # Start or restart collector
            if collector is None or collector.poll() is not None:

                if collector is not None:
                    print(
                        "[RUNNER] Collector exited. "
                        f"Exit code: {collector.returncode}"
                    )
                    time.sleep(RESTART_DELAY_SECONDS)

                collector = start_collector()

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

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:

        print("\n[RUNNER] Shutdown requested.")

    finally:

        stop_collector(collector)

        print("[RUNNER] Continuous paper trading stopped.")
        print("[RUNNER] Real order execution was never enabled.")


if __name__ == "__main__":
    main()
