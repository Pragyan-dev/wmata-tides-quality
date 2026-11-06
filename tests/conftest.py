"""Shared test helpers: build GTFS-RT feeds in code, and point the collector at tmp_path."""

import pytest
from google.transit import gtfs_realtime_pb2

from collector import config


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    """Send every collector write to a temp folder instead of data/."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw" / "wmata_bus")
    monkeypatch.setattr(config, "PARSED_DIR", tmp_path / "parsed")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "FETCH_LOG", tmp_path / "logs" / "fetches.csv")
    monkeypatch.setattr(config, "PID_FILE", tmp_path / "collector.pid")
    return tmp_path


def make_vehicle_feed(header_ts=1793976000) -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "1.0"
    feed.header.timestamp = header_ts

    full = feed.entity.add()
    full.id = "e1"
    vp = full.vehicle
    vp.trip.trip_id = "T100"
    vp.trip.route_id = "D80"
    vp.trip.start_date = "20261106"
    vp.vehicle.id = "7001"
    vp.position.latitude = 38.9
    vp.position.longitude = -77.03
    vp.position.bearing = 90
    vp.current_stop_sequence = 5
    vp.stop_id = "S1"
    vp.current_status = gtfs_realtime_pb2.VehiclePosition.IN_TRANSIT_TO
    vp.timestamp = header_ts - 10
    vp.occupancy_status = gtfs_realtime_pb2.VehiclePosition.FEW_SEATS_AVAILABLE

    # A vehicle with no trip and no position: optional fields must come back as None.
    bare = feed.entity.add()
    bare.id = "e2"
    bare.vehicle.vehicle.id = "7002"
    return feed.SerializeToString()


def make_trip_update_feed(header_ts=1793976000) -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "1.0"
    feed.header.timestamp = header_ts

    e = feed.entity.add()
    e.id = "t1"
    tu = e.trip_update
    tu.trip.trip_id = "T100"
    tu.trip.route_id = "D80"
    tu.vehicle.id = "7001"
    for seq, delay in [(5, 60), (6, 90)]:
        stu = tu.stop_time_update.add()
        stu.stop_sequence = seq
        stu.stop_id = f"S{seq}"
        stu.arrival.delay = delay
        stu.arrival.time = header_ts + 100 * seq

    canceled = feed.entity.add()
    canceled.id = "t2"
    canceled.trip_update.trip.trip_id = "T200"
    canceled.trip_update.trip.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.CANCELED
    return feed.SerializeToString()
