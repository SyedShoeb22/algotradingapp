import os
import sys

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.broker.angel_one import connect_angel_one
from app.broker.smartapi_compat import apply_smartapi_websocket_patch
from app.broker.ws_lock import AngelOneWebSocketLock


def main():
    apply_smartapi_websocket_patch()

    ws_lock = AngelOneWebSocketLock()
    if not ws_lock.acquire():
        print(
            "[ERROR] Another Angel One WebSocket process is currently active. "
            "Aborting test to prevent HTTP 429 connection limit lockout."
        )
        sys.exit(75)

    print("Connecting to Angel One...")

    try:
        session = connect_angel_one()

        ws = SmartWebSocketV2(
            session["jwt_token"],
            os.getenv("ANGEL_API_KEY"),
            session["client_code"],
            session["feed_token"],
            max_retry_attempt=0,
        )

        token_list = [
            {
                "exchangeType": 1,  # NSE cash
                "tokens": ["3045"],  # SBIN-EQ
            }
        ]

        def on_open(wsapp, *args, **kwargs):
            print("WebSocket connected.")
            print("Subscribing to SBIN-EQ...")
            ws.subscribe("sbin000001", 1, token_list)

        def on_data(wsapp, message, *args, **kwargs):
            if isinstance(message, dict):
                raw_price = message.get("last_traded_price")
                if raw_price is not None:
                    price = float(raw_price) / 100
                    print(
                        f"Symbol: SBIN-EQ | "
                        f"Token: {message.get('token')} | "
                        f"LTP: Rs. {price:.2f}"
                    )
                else:
                    print("Received message:", message)

        def on_error(wsapp_or_msg, error=None, *args, **kwargs):
            err = error if error is not None else wsapp_or_msg
            print("WebSocket error:", err)

        def on_close(wsapp, *args, **kwargs):
            print("WebSocket closed.", args, kwargs if kwargs else "")

        ws.on_open = on_open
        ws.on_data = on_data
        ws.on_error = on_error
        ws.on_close = on_close

        print("Starting market data stream...")
        print("Press CTRL+C to stop.")

        ws.connect()
    except KeyboardInterrupt:
        print("\nStopping stream...")
    finally:
        try:
            ws.close_connection()
        except Exception:
            pass
        ws_lock.release()


if __name__ == "__main__":
    main()
