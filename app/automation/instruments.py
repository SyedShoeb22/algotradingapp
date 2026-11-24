import json
import re
from pathlib import Path

MASTER_FILE = Path("data/OpenAPIScripMaster.json")


def normalize(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().strip())


def load_nse_equities():
    if not MASTER_FILE.exists():
        raise FileNotFoundError(
            "Instrument master missing. Run: "
            "python3 -m app.broker.download_instruments"
        )

    with MASTER_FILE.open(encoding="utf-8") as f:
        data = json.load(f)

    instruments = []

    for row in data:
        if row.get("exch_seg") != "NSE":
            continue

        symbol = str(row.get("symbol", "")).upper().strip()
        token = str(row.get("token", "")).strip()

        if symbol.endswith("-EQ") and token:
            instruments.append({
                "symbol": symbol,
                "token": token,
                "name": str(row.get("name", "")).strip(),
                "exchange": "NSE",
            })

    return instruments


def resolve_stock(query):
    query = query.strip()

    if not query:
        raise ValueError("Stock name cannot be empty.")

    stocks = load_nse_equities()
    key = normalize(query.removesuffix("-EQ"))

    exact = [
        x for x in stocks
        if normalize(x["symbol"].removesuffix("-EQ")) == key
        or normalize(x["name"]) == key
    ]

    if len(exact) == 1:
        return exact[0]

    if len(exact) > 1:
        raise ValueError(
            "Multiple exact matches: "
            + ", ".join(x["symbol"] for x in exact)
        )

    partial = [
        x for x in stocks
        if key in normalize(x["symbol"].removesuffix("-EQ"))
        or key in normalize(x["name"])
    ]

    if len(partial) == 1:
        return partial[0]

    if len(partial) > 1:
        raise ValueError(
            "Ambiguous stock. Matches: "
            + ", ".join(x["symbol"] for x in partial[:20])
        )

    raise LookupError(f"No NSE equity found for: {query}")
