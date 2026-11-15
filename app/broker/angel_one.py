
import os
import pyotp

from dotenv import load_dotenv
from SmartApi import SmartConnect

load_dotenv()


def connect_angel_one():

    api_key = os.getenv("ANGEL_API_KEY")
    client_code = os.getenv("ANGEL_CLIENT_CODE")
    pin = os.getenv("ANGEL_PIN")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    required = {
        "ANGEL_API_KEY": api_key,
        "ANGEL_CLIENT_CODE": client_code,
        "ANGEL_PIN": pin,
        "ANGEL_TOTP_SECRET": totp_secret,
    }

    missing = [
        key for key, value in required.items()
        if not value
    ]

    if missing:
        raise ValueError(
            "Missing configuration: " + ", ".join(missing)
        )

    smart_api = SmartConnect(api_key=api_key)

    current_totp = pyotp.TOTP(totp_secret).now()

    response = smart_api.generateSession(
        client_code,
        pin,
        current_totp
    )

    if not response or response.get("status") is not True:
        message = (
            response.get("message", "Authentication failed")
            if response else "No response from Angel One"
        )
        raise RuntimeError(message)

    session_data = response.get("data") or {}

    jwt_token = session_data.get("jwtToken")
    refresh_token = session_data.get("refreshToken")

    if not jwt_token or not refresh_token:
        raise RuntimeError("Authentication tokens missing")

    feed_token = (
        session_data.get("feedToken")
        or smart_api.getfeedToken()
    )

    if not feed_token:
        raise RuntimeError("Feed token unavailable")

    profile_response = smart_api.getProfile(refresh_token)

    if (
        not profile_response
        or profile_response.get("status") is not True
    ):
        raise RuntimeError("Unable to retrieve account profile")

    profile = profile_response.get("data") or {}

    return {
        "status": "success",
        "smart_api": smart_api,
        "jwt_token": jwt_token,
        "feed_token": feed_token,
        "client_code": client_code,
        "profile": profile,
    }

