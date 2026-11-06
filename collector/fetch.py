"""HTTP fetch with retry and backoff. Returns a result object and never raises."""

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

# Wait this many seconds before retry 1, 2, 3. Four attempts in total.
BACKOFF_SECONDS = [2, 4, 8]
RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    data: bytes | None  # response body, or None if every attempt failed
    status: int | None  # last HTTP status, or None if no response came back
    error: str | None
    duration_ms: int
    attempts: int


def fetch(url: str, api_key: str, timeout: float) -> FetchResult:
    start = time.monotonic()
    status = None
    error = None
    attempts = 0

    for attempt in range(len(BACKOFF_SECONDS) + 1):
        if attempt > 0:
            wait = BACKOFF_SECONDS[attempt - 1]
            log.warning("retry %d for %s in %ds after: %s", attempt, url, wait, error)
            time.sleep(wait)
        attempts += 1

        try:
            # The key goes in a header, not the URL, so it never appears in logs.
            response = requests.get(url, headers={"api_key": api_key}, timeout=timeout)
        except requests.RequestException as exc:
            status = None
            error = type(exc).__name__
            continue

        status = response.status_code
        if status == 200:
            return FetchResult(response.content, status, None, _ms_since(start), attempts)

        error = f"HTTP {status}"
        if status in (401, 403):
            log.error("%s from %s. Check WMATA_API_KEY in .env.", error, url)
            break
        if status not in RETRY_STATUSES:
            break

    log.error("giving up on %s after %d attempts: %s", url, attempts, error)
    return FetchResult(None, status, error, _ms_since(start), attempts)


def _ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
