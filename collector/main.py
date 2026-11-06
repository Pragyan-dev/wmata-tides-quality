"""The polling loop: every 30 seconds, fetch both feeds, save raw, parse, write Parquet.

Nothing inside one tick can stop the loop. Every error is caught, logged,
and recorded in data/logs/fetches.csv.
"""

import csv
import logging
import os
import signal
import sys
import time

from google.protobuf.message import DecodeError

from collector import config
from collector.fetch import fetch
from collector.parse import PARSERS, parse_feed
from collector.static import ensure_static
from collector.storage import (
    local_time,
    parquet_path,
    raw_path,
    write_bytes_atomic,
    write_parquet_atomic,
)

log = logging.getLogger("collector")

FETCH_LOG_COLUMNS = [
    "fetch_ts_utc",
    "fetch_time_local",
    "feed",
    "http_status",
    "bytes",
    "entity_count",
    "rows_written",
    "header_ts",
    "header_age_s",
    "duration_ms",
    "attempts",
    "error",
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def append_fetch_log(row: dict) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not config.FETCH_LOG.exists()
    with config.FETCH_LOG.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FETCH_LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def collect_feed(name: str, api_key: str, last_header_ts: dict) -> None:
    feed_cfg = config.FEEDS[name]
    fetch_ts = int(time.time())
    result = fetch(feed_cfg["url"], api_key, timeout=config.RT_TIMEOUT_SECONDS)
    row = {
        "fetch_ts_utc": fetch_ts,
        "fetch_time_local": local_time(fetch_ts).isoformat(timespec="seconds"),
        "feed": name,
        "http_status": result.status,
        "bytes": len(result.data) if result.data is not None else 0,
        "duration_ms": result.duration_ms,
        "attempts": result.attempts,
        "error": result.error,
    }

    if result.data is not None:
        # Save raw bytes first, so a parse bug never loses data.
        write_bytes_atomic(raw_path(config.RAW_DIR, feed_cfg["raw_folder"], fetch_ts), result.data)
        try:
            feed = parse_feed(result.data)
        except DecodeError:
            row["error"] = "protobuf decode error"
            log.error("%s: could not decode %d bytes", name, len(result.data))
        else:
            build_rows, schema = PARSERS[name]
            rows = build_rows(feed, fetch_ts)
            write_parquet_atomic(parquet_path(config.PARSED_DIR, name, fetch_ts), rows, schema)

            header_ts = feed.header.timestamp if feed.header.HasField("timestamp") else None
            row.update(
                entity_count=len(feed.entity),
                rows_written=len(rows),
                header_ts=header_ts,
                header_age_s=fetch_ts - header_ts if header_ts else None,
            )
            if len(feed.entity) == 0:
                log.warning("%s: empty feed (0 entities)", name)
            if header_ts is not None and header_ts == last_header_ts.get(name):
                log.warning("%s: stale feed, header timestamp %d unchanged", name, header_ts)
            last_header_ts[name] = header_ts
            log.info(
                "%s: %d entities, %d rows, %d KB, %d ms",
                name,
                len(feed.entity),
                len(rows),
                len(result.data) // 1024,
                result.duration_ms,
            )

    append_fetch_log(row)


def check_static(api_key: str) -> None:
    now_ts = int(time.time())
    result = ensure_static(api_key, config.RAW_DIR, now_ts)
    if result is None:
        return
    append_fetch_log(
        {
            "fetch_ts_utc": now_ts,
            "fetch_time_local": local_time(now_ts).isoformat(timespec="seconds"),
            "feed": "static",
            "http_status": result.status,
            "bytes": len(result.data) if result.data is not None else 0,
            "duration_ms": result.duration_ms,
            "attempts": result.attempts,
            "error": result.error,
        }
    )


def next_aligned(now: float) -> float:
    """Next :00 or :30 second mark after now."""
    return (int(now) // config.POLL_SECONDS + 1) * config.POLL_SECONDS


def _exit_on_sigterm(signum, frame):
    raise SystemExit(0)


def run() -> None:
    setup_logging()
    api_key = config.get_api_key()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    log.info("collector started, pid %d, polling every %ds", os.getpid(), config.POLL_SECONDS)

    last_header_ts: dict = {}
    next_static_check = 0.0
    next_tick = next_aligned(time.time())
    try:
        while True:
            time.sleep(max(0.0, next_tick - time.time()))

            if time.time() >= next_static_check:
                try:
                    check_static(api_key)
                except Exception:
                    log.exception("static GTFS check failed")
                next_static_check = time.time() + config.STATIC_CHECK_SECONDS

            for name in config.FEEDS:
                try:
                    collect_feed(name, api_key, last_header_ts)
                except Exception:
                    log.exception("%s: unexpected error, continuing", name)

            next_tick += config.POLL_SECONDS
            if next_tick <= time.time():
                skipped = int((time.time() - next_tick) // config.POLL_SECONDS) + 1
                log.warning("tick ran long, skipping %d poll(s)", skipped)
                next_tick = next_aligned(time.time())
    except (KeyboardInterrupt, SystemExit):
        log.info("collector stopping")
    finally:
        config.PID_FILE.unlink(missing_ok=True)
