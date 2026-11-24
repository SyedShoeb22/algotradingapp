
import os
import queue
import signal
import sys
import threading
import time

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.broker.angel_one import connect_angel_one
from app.broker.smartapi_compat import apply_smartapi_websocket_patch
from app.broker.ws_lock import AngelOneWebSocketLock
from app.core.database import SessionLocal
from app.core.models import MarketTick


# SBI configuration
SYMBOL = "SBIN-EQ"
TOKEN = os.getenv("SBI_TOKEN")
EXCHANGE = "NSE"
EXCHANGE_TYPE = 1  # NSE cash market
SUBSCRIPTION_MODE = 1  # LTP

tick_queue = queue.Queue()
stop_event = threading.Event()


def database_writer():
    """Save incoming SBI market ticks in batches."""

    batch = []
    last_flush = time.monotonic()

    while not stop_event.is_set() or not tick_queue.empty():

        try:
            tick = tick_queue.get(timeout=0.5)
            batch.append(tick)
            tick_queue.task_done()

        except queue.Empty:
            pass

        should_flush = (
            len(batch) >= 50
            or (
                batch
                and time.monotonic() - last_flush >= 1
            )
            or (
                batch
                and stop_event.is_set()
                and tick_queue.empty()
            )
        )

        if should_flush:
            try:
                with SessionLocal() as db:
                    records = [
                        MarketTick(**item)
                        for item in batch
                    ]

                    db.add_all(records)
                    db.commit()

                print(f"Saved {len(batch)} SBI market ticks.")

                batch.clear()
                last_flush = time.monotonic()

            except Exception as error:
                print("Database error while saving ticks:", error)
                batch.clear()
                last_flush = time.monotonic()


def main():

    if not TOKEN:
        raise RuntimeError(
            "SBI_TOKEN is missing. Add your SBI NSE instrument "
            "token to the .env file."
        )

    # Reset state in case main() is called again in this process.
    stop_event.clear()

    # Graceful SIGTERM handling
    def _sigterm_handler(signum, frame):
        stop_event.set()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # Apply compatibility patch for websocket-client >= 1.0
    apply_smartapi_websocket_patch()

    # Acquire shared cross-process lock BEFORE authenticating or opening connection
    ws_lock = AngelOneWebSocketLock()
    if not ws_lock.acquire():
        print(
            "[COLLECTOR] Another Angel One WebSocket collector process is currently active. "
            "Exiting immediately to prevent HTTP 429 connection limit lockout."
        )
        sys.exit(75)

    print("===================================")
    print("SBI LIVE MARKET-DATA COLLECTOR")
    print("===================================")
    print(f"Symbol: {SYMBOL}")
    print(f"Token: {TOKEN}")
    print(f"Exchange: {EXCHANGE}")
    print("Authenticating with Angel One...")

    session = connect_angel_one()

    ws = SmartWebSocketV2(
        session["jwt_token"],
        os.getenv("ANGEL_API_KEY"),
        session["client_code"],
        session["feed_token"],
        max_retry_attempt=0
    )

    token_list = [
        {
            "exchangeType": EXCHANGE_TYPE,
            "tokens": [TOKEN]
        }
    ]

    def on_open(wsapp, *args, **kwargs):
        print("WebSocket connected.")
        print(f"Subscribing to {SYMBOL}...")

        ws.subscribe(
            "sbi_collector01",
            SUBSCRIPTION_MODE,
            token_list
        )

    def on_data(wsapp, message, *args, **kwargs):

        if not isinstance(message, dict):
            return

        raw_price = message.get("last_traded_price")

        if raw_price is None:
            return

        try:
            ltp = float(raw_price) / 100

            received_tick = {
                "symbol": SYMBOL,
                "token": str(message.get("token", TOKEN)),
                "exchange": EXCHANGE,
                "ltp": ltp,
                "exchange_timestamp": (
                    str(message.get("exchange_timestamp"))
                    if message.get("exchange_timestamp") is not None
                    else None
                )
            }

            tick_queue.put(received_tick)

            print(f"{SYMBOL} | LTP: Rs. {ltp:.2f}")

        except (TypeError, ValueError) as error:
            print("Invalid market tick:", error)

    def on_error(wsapp_or_msg, error=None, *args, **kwargs):
        err_text = str(error) if error is not None else str(wsapp_or_msg)
        print("WebSocket error:", err_text)

    def on_close(wsapp, *args, **kwargs):
        code = args[0] if len(args) > 0 else kwargs.get("close_status_code")
        reason = args[1] if len(args) > 1 else kwargs.get("close_reason")
        info = f" (code: {code}, reason: {reason})" if (code or reason) else ""
        print(f"WebSocket connection closed{info}.")

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close

    writer = threading.Thread(
        target=database_writer,
        daemon=True
    )

    writer.start()

    print("Starting SBI market-data collector...")
    print("Press CTRL+C to stop.")

    try:
        ws.connect()

    except KeyboardInterrupt:
        print("\nStopping collector...")

    finally:
        try:
            ws.close_connection()
        except Exception as error:
            print("WebSocket shutdown message:", error)

        stop_event.set()
        writer.join(timeout=15)
        if writer.is_alive():
            print(
                "[COLLECTOR] CRITICAL: Writer thread did not terminate within timeout; "
                "retaining Angel One lock for safety."
            )
        else:
            ws_lock.release()

        print("SBI market-data collector stopped.")


if __name__ == "__main__":
    main()

