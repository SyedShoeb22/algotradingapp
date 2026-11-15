
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.broker.angel_one import connect_angel_one


def main():
    print("Connecting to Angel One...")

    session = connect_angel_one()

    ws = SmartWebSocketV2(
        session["jwt_token"],
        __import__("os").getenv("ANGEL_API_KEY"),
        session["client_code"],
        session["feed_token"],
        max_retry_attempt=0
    )

    token_list = [
        {
            "exchangeType": 1,  # NSE cash
            "tokens": ["3045"]  # SBIN-EQ
        }
    ]

    def on_open(wsapp):
        print("WebSocket connected.")
        print("Subscribing to SBIN-EQ...")
        ws.subscribe("sbin000001", 1, token_list)

    def on_data(wsapp, message):
        raw_price = message.get("last_traded_price")

        if raw_price is not None:
            price = raw_price / 100

            print(
                f"Symbol: SBIN-EQ | "
                f"Token: {message.get('token')} | "
                f"LTP: Rs. {price:.2f}"
            )
        else:
            print("Received message:", message)

    def on_error(wsapp, error):
        print("WebSocket error:", error)

    def on_close(wsapp):
        print("WebSocket closed.")

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close

    print("Starting market data stream...")
    print("Press CTRL+C to stop.")

    try:
        ws.connect()
    except KeyboardInterrupt:
        print("\nStopping stream...")
    finally:
        ws.close_connection()


if __name__ == "__main__":
    main()

