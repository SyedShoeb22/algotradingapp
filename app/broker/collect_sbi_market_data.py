
import os
import time
import queue
import threading

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.broker.angel_one import connect_angel_one
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

    def on_open(wsapp):
        print("WebSocket connected.")
        print(f"Subscribing to {SYMBOL}...")

        ws.subscribe(
            "kross_collector01",
            SUBSCRIPTION_MODE,
            token_list
        )

    def on_data(wsapp, message):

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

    def on_error(wsapp, error):
        print("WebSocket error:", error)

    def on_close(wsapp):
        print("WebSocket connection closed.")

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

        print("SBI market-data collector stopped.")


if __name__ == "__main__":
    main()

