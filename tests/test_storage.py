from pathlib import Path

from collector.storage import parquet_path, raw_path, static_path, write_bytes_atomic

ROOT = Path("/r")


def test_raw_path_matches_gtfs_rt_to_tides_layout():
    # 2026-11-06 14:40:00 UTC is 09:40:00 in New York (EST, UTC-5).
    p = raw_path(ROOT, "vehicle_positions_url", 1793976000)
    assert p == ROOT / "2026-11-06/vehicle_positions_url/1793976000-2026-11-06-09-40-00.pb"


def test_date_partition_uses_new_york_date_not_utc():
    # 2026-11-07 03:00 UTC is still 2026-11-06 22:00 in New York.
    p = parquet_path(ROOT, "trip_updates", 1794020400)
    assert p == ROOT / "trip_updates/date=2026-11-06/1794020400.parquet"


def test_dst_fall_back_hour_gives_unique_names():
    # 2026-11-01: 01:30 local happens twice, once in EDT and once in EST.
    edt = raw_path(ROOT, "trip_updates_url", 1793511000)  # 05:30 UTC = 01:30 EDT
    est = raw_path(ROOT, "trip_updates_url", 1793514600)  # 06:30 UTC = 01:30 EST
    assert edt.name.endswith("2026-11-01-01-30-00.pb")
    assert est.name.endswith("2026-11-01-01-30-00.pb")
    assert edt != est


def test_static_path():
    assert static_path(ROOT, "2026-11-06") == ROOT / "2026-11-06/schedule/gtfs.zip"


def test_atomic_write_leaves_no_partial_file(tmp_path):
    target = tmp_path / "a" / "b.pb"
    write_bytes_atomic(target, b"abc")
    assert target.read_bytes() == b"abc"
    assert [p.name for p in target.parent.iterdir()] == ["b.pb"]
