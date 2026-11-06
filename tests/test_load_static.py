import csv
import hashlib
import io
import zipfile

import duckdb

from collector.load_static import load_static


def write_version(raw_dir, date, files):
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    data = zbuf.getvalue()
    folder = raw_dir / date / "schedule"
    folder.mkdir(parents=True)
    (folder / "gtfs.zip").write_bytes(data)
    (folder / "gtfs.zip.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")
    return hashlib.sha256(data).hexdigest()[:12]


GTFS = {
    # Leading byte order mark and an unpadded hour, both seen in real feeds.
    "stop_times.txt": "﻿trip_id,arrival_time,stop_id,stop_sequence\nT1,9:59:59,S1,1\n",
    "routes.txt": "route_id,route_type\nR1,3\n",
}


def test_same_zip_on_two_dates_is_stored_once(tmp_path):
    raw, static = tmp_path / "raw", tmp_path / "static"
    v1 = write_version(raw, "2026-11-06", GTFS)
    v2 = write_version(raw, "2026-11-07", GTFS)
    assert v1 == v2

    load_static(raw, static)

    assert [p.name for p in static.iterdir() if p.is_dir()] == [v1]
    rows = list(csv.DictReader((static / "feed_versions.csv").open()))
    assert rows == [
        {"collection_date": "2026-11-06", "feed_version": v1},
        {"collection_date": "2026-11-07", "feed_version": v1},
    ]


def test_columns_stay_text_and_bom_is_removed(tmp_path):
    raw, static = tmp_path / "raw", tmp_path / "static"
    version = write_version(raw, "2026-11-06", GTFS)
    load_static(raw, static)

    con = duckdb.connect()
    path = static / version / "stop_times.parquet"
    rel = con.read_parquet(str(path))
    assert rel.columns[0] == "trip_id"
    assert {str(t) for t in rel.types} == {"VARCHAR"}
    assert rel.fetchall() == [("T1", "9:59:59", "S1", "1")]
