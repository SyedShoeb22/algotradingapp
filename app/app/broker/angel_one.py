"""Angel One SmartAPI session management (TOTP-based login)."""

import os

import pyotp
from dotenv import load_dotenv

from app.core.config import (
    ANGEL_API_KEY,
    ANGEL_CLIENT_CODE,
    ANGEL_PIN,
    ANGEL_TOTP_SECRET,
    BASE_DIR,
)

load_dotenv(BASE_DIR / ".env")


def connect_angel_one():
    """Authenticate with Angel One and return a session bundle.

    Raises a clear error when a credential is missing so the caller can
    tell the user to fill in their ``.env`` file.
    """

    from SmartApi import SmartConnect  # imported lazily (heavy dependency)

    required = {
        "ANGEL_API_KEY": ANGEL_API_KEY or os.getenv("ANGEL_API_KEY"),
        "ANGEL_CLIENT_CODE": ANGEL_CLIENT_CODE or os.getenv("ANGEL_CLIENT_CODE"),
        "ANGEL_PIN": ANGEL_PIN or os.getenv("ANGEL_PIN"),
        "ANGEL_TOTP_SECRET": ANGEL_TOTP_SECRET or os.getenv("ANGEL_TOTP_SECRET"),
    }

    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(
            "Missing Angel One configuration: "
            + ", ".join(missing)
            + ". Add them to the .env file in the project root."
        )

    api_key = required["ANGEL_API_KEY"]
    client_code = required["ANGEL_CLIENT_CODE"]
    pin = required["ANGEL_PIN"]
    totp_secret = required["ANGEL_TOTP_SECRET"]

    smart_api = SmartConnect(api_key=api_key)

    current_totp = pyotp.TOTP(totp_secret).now()

    response = smart_api.generateSession(client_code, pin, current_totp)

    if not response or response.get("status") is not True:
        message = (
            response.get("message", "Authentication failed")
            if response
            else "No response from Angel One"
        )
        raise RuntimeError(message)

    session_data = response.get("data") or {}

    jwt_token = session_data.get("jwtToken")
    refresh_token = session_data.get("refreshToken")

    if not jwt_token or not refresh_token:
        raise RuntimeError("Authentication tokens missing")

    feed_token = session_data.get("feedToken") or smart_api.getfeedToken()

    if not feed_token:
        raise RuntimeError("Feed token unavailable")

    profile_response = smart_api.getProfile(refresh_token)

    if not profile_response or profile_response.get("status") is not True:
        raise RuntimeError("Unable to retrieve account profile")

    return {
        "status": "success",
        "smart_api": smart_api,
        "jwt_token": jwt_token,
        "feed_token": feed_token,
        "client_code": client_code,
        "profile": profile_response.get("data") or {},
    }
