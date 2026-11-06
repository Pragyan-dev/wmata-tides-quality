"""`python -m collector reparse --date YYYY-MM-DD`: rebuild Parquet from raw .pb files.

Raw protobuf is the source of truth. Run this after changing parse.py.
"""

import logging

from google.protobuf.message import DecodeError

from collector import config
from collector.parse import PARSERS, parse_feed
from collector.storage import parquet_path, write_parquet_atomic

log = logging.getLogger(__name__)


def reparse(date: str) -> None:
    for name, feed_cfg in config.FEEDS.items():
        build_rows, schema = PARSERS[name]
        files = sorted((config.RAW_DIR / date / feed_cfg["raw_folder"]).glob("*.pb"))
        bad = 0
        for path in files:
            fetch_ts = int(path.stem.split("-")[0])
            try:
                feed = parse_feed(path.read_bytes())
            except DecodeError:
                bad += 1
                continue
            rows = build_rows(feed, fetch_ts)
            write_parquet_atomic(parquet_path(config.PARSED_DIR, name, fetch_ts), rows, schema)
        print(f"{name}: reparsed {len(files) - bad} files, {bad} could not be decoded")
