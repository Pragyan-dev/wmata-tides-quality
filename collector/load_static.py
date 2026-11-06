"""`python -m collector load-static`: unpack each distinct static GTFS version to Parquet.

The collector saves one gtfs.zip per date, but most days the file is identical.
This step stores each distinct version once, under data/static/<version>/,
where <version> is the first 12 characters of the zip's SHA-256. It also writes
data/static/feed_versions.csv, which maps every collection date to its version.
dbt reads both.
"""

import csv
import zipfile
from pathlib import Path

import duckdb

from collector import config

STATIC_DIR = config.DATA_DIR / "static"
GTFS_FILES = [
    "agency",
    "routes",
    "trips",
    "stops",
    "stop_times",
    "shapes",
    "calendar",
    "calendar_dates",
    "feed_info",
]


def load_static(raw_dir: Path = config.RAW_DIR, static_dir: Path = STATIC_DIR) -> None:
    static_dir.mkdir(parents=True, exist_ok=True)
    mapping = []
    for zip_path in sorted(raw_dir.glob("*/schedule/gtfs.zip")):
        date = zip_path.parent.parent.name
        sha_file = zip_path.with_name("gtfs.zip.sha256")
        version = sha_file.read_text().strip()[:12]
        mapping.append({"collection_date": date, "feed_version": version})

        out_dir = static_dir / version
        if (out_dir / "_complete").exists():
            continue
        out_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for name in GTFS_FILES:
                if f"{name}.txt" not in zf.namelist():
                    continue
                _csv_to_parquet(zf.read(f"{name}.txt"), out_dir / f"{name}.parquet")
        (out_dir / "_complete").write_text("")
        print(f"unpacked static GTFS {version} (first seen {date})")

    with (static_dir / "feed_versions.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["collection_date", "feed_version"])
        writer.writeheader()
        writer.writerows(mapping)
    print(f"{len(mapping)} dates mapped to {len({m['feed_version'] for m in mapping})} versions")


def _csv_to_parquet(data: bytes, out_path: Path) -> None:
    """Every column stays text here. dbt staging casts types, so casts are visible in SQL."""
    tmp_csv = out_path.with_suffix(".csv.tmp")
    tmp_csv.write_bytes(data.lstrip(b"\xef\xbb\xbf"))  # drop a UTF-8 byte order mark if present
    try:
        con = duckdb.connect()
        con.read_csv(str(tmp_csv), all_varchar=True, header=True).write_parquet(str(out_path))
    finally:
        tmp_csv.unlink(missing_ok=True)


if __name__ == "__main__":
    load_static()
