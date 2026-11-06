"""One full tick against fake HTTP responses, checking files and fetches.csv."""

import csv

import pyarrow.parquet as pq

from collector import main
from collector.fetch import FetchResult
from tests.conftest import make_trip_update_feed, make_vehicle_feed


def fake_fetch_returning(payloads):
    def _fetch(url, api_key, timeout):
        return payloads[url]

    return _fetch


def test_collect_feed_writes_raw_parquet_and_log(data_dirs, monkeypatch):
    from collector import config

    payloads = {
        config.FEEDS["vehicle_positions"]["url"]: FetchResult(make_vehicle_feed(), 200, None, 5, 1),
        config.FEEDS["trip_updates"]["url"]: FetchResult(make_trip_update_feed(), 200, None, 5, 1),
    }
    monkeypatch.setattr(main, "fetch", fake_fetch_returning(payloads))

    seen = {}
    for name in config.FEEDS:
        main.collect_feed(name, "k", seen)

    assert len(list(config.RAW_DIR.glob("*/vehicle_positions_url/*.pb"))) == 1
    assert len(list(config.RAW_DIR.glob("*/trip_updates_url/*.pb"))) == 1
    vp_files = list(config.PARSED_DIR.glob("vehicle_positions/date=*/*.parquet"))
    assert pq.read_table(vp_files[0]).num_rows == 2

    log_rows = list(csv.DictReader(config.FETCH_LOG.open()))
    assert [r["feed"] for r in log_rows] == ["vehicle_positions", "trip_updates"]
    assert log_rows[1]["rows_written"] == "3"
    assert log_rows[0]["error"] == ""


def test_failed_fetch_and_bad_bytes_are_logged_not_raised(data_dirs, monkeypatch):
    from collector import config

    payloads = {
        config.FEEDS["vehicle_positions"]["url"]: FetchResult(None, 503, "HTTP 503", 5, 4),
        config.FEEDS["trip_updates"]["url"]: FetchResult(b"\xff garbage", 200, None, 5, 1),
    }
    monkeypatch.setattr(main, "fetch", fake_fetch_returning(payloads))

    for name in config.FEEDS:
        main.collect_feed(name, "k", {})

    log_rows = list(csv.DictReader(config.FETCH_LOG.open()))
    assert log_rows[0]["error"] == "HTTP 503"
    assert log_rows[1]["error"] == "protobuf decode error"
    # Bad bytes are still kept raw, so they can be inspected later.
    assert len(list(config.RAW_DIR.glob("*/trip_updates_url/*.pb"))) == 1


def test_next_aligned_lands_on_00_or_30():
    assert main.next_aligned(100.0) == 120
    assert main.next_aligned(120.0) == 150
    assert main.next_aligned(149.9) == 150
