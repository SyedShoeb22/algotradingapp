
import requests
import time
from pathlib import Path

URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "OpenAPIScripMaster.json"

DATA_DIR.mkdir(exist_ok=True)

for attempt in range(1, 6):
    try:
        print(f"Download attempt {attempt}/5")

        response = requests.get(
            URL,
            timeout=(20, 180),
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True
        )

        response.raise_for_status()

        temp_file = OUTPUT_FILE.with_suffix(".tmp")
        downloaded = 0

        with open(temp_file, "wb") as file:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    file.write(chunk)
                    downloaded += len(chunk)

        import json

        with open(temp_file, "r", encoding="utf-8") as file:
            instruments = json.load(file)

        if not isinstance(instruments, list) or not instruments:
            raise ValueError("Downloaded instrument data is invalid.")

        temp_file.replace(OUTPUT_FILE)

        print("Download successful!")
        print(f"Total instruments: {len(instruments)}")
        print(f"Saved to: {OUTPUT_FILE}")
        break

    except Exception as error:
        print("Download failed:", error)

        if attempt < 5:
            time.sleep(5)

else:
    print("Could not download the instrument master.")

