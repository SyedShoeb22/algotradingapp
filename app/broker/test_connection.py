
from app.broker.angel_one import connect_angel_one


if __name__ == "__main__":

    try:
        result = connect_angel_one()

        profile = result["profile"]

        print("\n================================")
        print("ANGEL ONE CONNECTION SUCCESSFUL")
        print("================================")

        print("Authentication: Successful")
        print("Profile retrieval: Successful")

        print(
            "Client name:",
            profile.get("name", "Not provided")
        )

        print(
            "Enabled exchanges:",
            profile.get("exchanges", [])
        )

        print("Feed token: Received (hidden)")
        print("JWT token: Received (hidden)")

    except Exception as error:

        print("\nANGEL ONE CONNECTION FAILED")
        print("Error:", str(error))

