"""File paths and atomic writes for raw protobuf, Parquet, and static GTFS."""

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from collector import config


def local_time(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, config.AGENCY_TZ)


def local_date(epoch: int) -> str:
    return f"{local_time(epoch):%Y-%m-%d}"


def raw_path(root: Path, raw_folder: str, fetch_ts: int) -> Path:
    """<root>/<local date>/<raw_folder>/<epoch>-<local YYYY-MM-DD-HH-MM-SS>.pb

    The epoch prefix keeps names unique across the DST fall-back hour,
    when the same local clock time happens twice.
    """
    t = local_time(fetch_ts)
    return root / f"{t:%Y-%m-%d}" / raw_folder / f"{fetch_ts}-{t:%Y-%m-%d-%H-%M-%S}.pb"


def parquet_path(root: Path, feed: str, fetch_ts: int) -> Path:
    return root / feed / f"date={local_date(fetch_ts)}" / f"{fetch_ts}.parquet"


def static_path(root: Path, date: str) -> Path:
    return root / date / "schedule" / "gtfs.zip"


def _partial(path: Path) -> Path:
    return path.with_name(f".{path.name}.partial")


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write to a temp file, then rename. A crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _partial(path)
    tmp.write_bytes(data)
    tmp.replace(path)


def write_parquet_atomic(path: Path, rows: list[dict], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _partial(path)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp)
    tmp.replace(path)
