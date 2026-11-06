"""All collector settings in one place."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Raw layout matches evansiroky/gtfs-rt-to-tides:
#   raw/wmata_bus/<YYYY-MM-DD>/<feed folder>/<epoch>-<YYYY-MM-DD-HH-MM-SS>.pb
RAW_DIR = DATA_DIR / "raw" / "wmata_bus"
PARSED_DIR = DATA_DIR / "parsed"
LOG_DIR = DATA_DIR / "logs"
FETCH_LOG = LOG_DIR / "fetches.csv"
PID_FILE = DATA_DIR / "collector.pid"

AGENCY_TZ = ZoneInfo("America/New_York")

POLL_SECONDS = 30
STATIC_CHECK_SECONDS = 3600
RT_TIMEOUT_SECONDS = 10
STATIC_TIMEOUT_SECONDS = 120

# Endpoints from WMATA's developer portal, API "GTFS".
# Auth is the "api_key" request header.
BASE_URL = "https://api.wmata.com/gtfs"
STATIC_URL = f"{BASE_URL}/bus-gtfs-static.zip"
FEEDS = {
    "vehicle_positions": {
        "url": f"{BASE_URL}/bus-gtfsrt-vehiclepositions.pb",
        "raw_folder": "vehicle_positions_url",
    },
    "trip_updates": {
        "url": f"{BASE_URL}/bus-gtfsrt-tripupdates.pb",
        "raw_folder": "trip_updates_url",
    },
}


def get_api_key() -> str:
    """Read the key from .env. Never log or print the returned value."""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("WMATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "WMATA_API_KEY is not set. Copy .env.example to .env and paste your key."
        )
    return key
