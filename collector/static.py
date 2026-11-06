"""Daily download of the WMATA bus static GTFS zip, saved once per local date."""

import hashlib
import io
import logging
import zipfile
from pathlib import Path

from collector import config
from collector.fetch import FetchResult, fetch
from collector.storage import local_date, static_path, write_bytes_atomic

log = logging.getLogger(__name__)

REQUIRED_FILES = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}


def ensure_static(api_key: str, root: Path, now_ts: int) -> FetchResult | None:
    """Download today's static GTFS if it is not saved yet.

    Returns the fetch result, or None if today's file already exists.
    Next to gtfs.zip it writes gtfs.zip.sha256, so later steps can tell
    whether the schedule changed from one day to the next.
    """
    path = static_path(root, local_date(now_ts))
    if path.exists():
        return None

    result = fetch(config.STATIC_URL, api_key, timeout=config.STATIC_TIMEOUT_SECONDS)
    if result.data is None:
        return result

    missing = _missing_gtfs_files(result.data)
    if missing:
        result.error = f"not a valid GTFS zip, missing: {sorted(missing)}"
        log.error("static GTFS rejected: %s", result.error)
        result.data = None
        return result

    digest = hashlib.sha256(result.data).hexdigest()
    previous = _latest_previous_digest(root, path)
    write_bytes_atomic(path, result.data)
    write_bytes_atomic(path.with_name("gtfs.zip.sha256"), f"{digest}\n".encode())

    changed = "first version" if previous is None else str(previous != digest)
    log.info(
        "saved static GTFS %s (%d bytes, sha256 %s..., changed: %s)",
        path,
        len(result.data),
        digest[:12],
        changed,
    )
    return result


def _missing_gtfs_files(data: bytes) -> set[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = {Path(n).name for n in zf.namelist()}
    except zipfile.BadZipFile:
        return REQUIRED_FILES
    return REQUIRED_FILES - names


def _latest_previous_digest(root: Path, today_path: Path) -> str | None:
    digests = sorted(root.glob("*/schedule/gtfs.zip.sha256"))
    digests = [p for p in digests if p.parent != today_path.parent]
    return digests[-1].read_text().strip() if digests else None
