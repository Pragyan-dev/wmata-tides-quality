import pyarrow as pa
import pytest
from google.protobuf.message import DecodeError

from collector.parse import (
    TRIP_UPDATES_SCHEMA,
    VEHICLE_POSITIONS_SCHEMA,
    parse_feed,
    trip_update_rows,
    vehicle_position_rows,
)
from tests.conftest import make_trip_update_feed, make_vehicle_feed


def test_vehicle_positions_full_entity():
    rows = vehicle_position_rows(parse_feed(make_vehicle_feed()), fetch_ts=1793976005)
    assert len(rows) == 2
    r = rows[0]
    assert r["fetch_ts_utc"] == 1793976005
    assert r["feed_header_ts"] == 1793976000
    assert r["trip_id"] == "T100"
    assert r["route_id"] == "D80"
    assert r["vehicle_id"] == "7001"
    assert r["latitude"] == pytest.approx(38.9, abs=1e-5)
    assert r["longitude"] == pytest.approx(-77.03, abs=1e-5)
    assert r["current_status"] == "IN_TRANSIT_TO"
    assert r["occupancy_status"] == "FEW_SEATS_AVAILABLE"
    assert r["vehicle_ts"] == 1793975990


def test_vehicle_positions_missing_fields_are_none_not_zero():
    r = vehicle_position_rows(parse_feed(make_vehicle_feed()), fetch_ts=1)[1]
    assert r["vehicle_id"] == "7002"
    for field in [
        "trip_id",
        "route_id",
        "latitude",
        "longitude",
        "speed",
        "vehicle_ts",
        "current_status",
        "current_stop_sequence",
    ]:
        assert r[field] is None, field


def test_trip_updates_one_row_per_stop_and_keeps_canceled_trip():
    rows = trip_update_rows(parse_feed(make_trip_update_feed()), fetch_ts=1)
    assert [(r["trip_id"], r.get("stop_sequence")) for r in rows] == [
        ("T100", 5),
        ("T100", 6),
        ("T200", None),
    ]
    assert rows[1]["arrival_delay"] == 90
    assert rows[1]["departure_time"] is None
    assert rows[2]["trip_schedule_relationship"] == "CANCELED"


def test_rows_fit_the_parquet_schemas():
    vp = vehicle_position_rows(parse_feed(make_vehicle_feed()), fetch_ts=1)
    tu = trip_update_rows(parse_feed(make_trip_update_feed()), fetch_ts=1)
    assert pa.Table.from_pylist(vp, schema=VEHICLE_POSITIONS_SCHEMA).num_rows == 2
    assert pa.Table.from_pylist(tu, schema=TRIP_UPDATES_SCHEMA).num_rows == 3
    # An empty feed still produces a typed, empty table.
    assert pa.Table.from_pylist([], schema=VEHICLE_POSITIONS_SCHEMA).num_columns == 22


def test_bad_bytes_raise_decode_error():
    with pytest.raises(DecodeError):
        parse_feed(b"\xff\xff not a protobuf")
