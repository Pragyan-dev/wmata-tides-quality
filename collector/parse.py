"""Turn GTFS-RT protobuf bytes into flat rows for Parquet.

Optional protobuf fields that are not set become None, not 0. This matters
for data quality checks later: a missing position is different from (0, 0).
"""

import pyarrow as pa
from google.transit import gtfs_realtime_pb2

VEHICLE_POSITIONS_SCHEMA = pa.schema(
    [
        ("fetch_ts_utc", pa.int64()),
        ("feed_header_ts", pa.int64()),
        ("entity_id", pa.string()),
        ("trip_id", pa.string()),
        ("route_id", pa.string()),
        ("direction_id", pa.int32()),
        ("start_date", pa.string()),
        ("start_time", pa.string()),
        ("trip_schedule_relationship", pa.string()),
        ("vehicle_id", pa.string()),
        ("vehicle_label", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("bearing", pa.float64()),
        ("speed", pa.float64()),
        ("odometer", pa.float64()),
        ("current_stop_sequence", pa.int64()),
        ("stop_id", pa.string()),
        ("current_status", pa.string()),
        ("vehicle_ts", pa.int64()),
        ("congestion_level", pa.string()),
        ("occupancy_status", pa.string()),
    ]
)

TRIP_UPDATES_SCHEMA = pa.schema(
    [
        ("fetch_ts_utc", pa.int64()),
        ("feed_header_ts", pa.int64()),
        ("entity_id", pa.string()),
        ("trip_id", pa.string()),
        ("route_id", pa.string()),
        ("direction_id", pa.int32()),
        ("start_date", pa.string()),
        ("start_time", pa.string()),
        ("trip_schedule_relationship", pa.string()),
        ("vehicle_id", pa.string()),
        ("trip_update_ts", pa.int64()),
        ("trip_delay", pa.int64()),
        ("stop_sequence", pa.int64()),
        ("stop_id", pa.string()),
        ("arrival_time", pa.int64()),
        ("arrival_delay", pa.int64()),
        ("departure_time", pa.int64()),
        ("departure_delay", pa.int64()),
        ("stu_schedule_relationship", pa.string()),
    ]
)


def parse_feed(data: bytes) -> gtfs_realtime_pb2.FeedMessage:
    """Raises google.protobuf.message.DecodeError on bad bytes."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)
    return feed


def _get(msg, field):
    """Field value if set, else None."""
    return getattr(msg, field) if msg.HasField(field) else None


def _enum(msg, field):
    """Enum name (e.g. 'IN_TRANSIT_TO') if set, else None."""
    if not msg.HasField(field):
        return None
    number = getattr(msg, field)
    value = msg.DESCRIPTOR.fields_by_name[field].enum_type.values_by_number.get(number)
    return value.name if value else str(number)


def _trip_fields(trip) -> dict:
    return {
        "trip_id": _get(trip, "trip_id"),
        "route_id": _get(trip, "route_id"),
        "direction_id": _get(trip, "direction_id"),
        "start_date": _get(trip, "start_date"),
        "start_time": _get(trip, "start_time"),
        "trip_schedule_relationship": _enum(trip, "schedule_relationship"),
    }


def vehicle_position_rows(feed, fetch_ts: int) -> list[dict]:
    header_ts = _get(feed.header, "timestamp")
    rows = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vp = entity.vehicle
        has_pos = vp.HasField("position")
        pos = vp.position
        rows.append(
            {
                "fetch_ts_utc": fetch_ts,
                "feed_header_ts": header_ts,
                "entity_id": entity.id,
                **_trip_fields(vp.trip),
                "vehicle_id": _get(vp.vehicle, "id"),
                "vehicle_label": _get(vp.vehicle, "label"),
                "latitude": pos.latitude if has_pos else None,
                "longitude": pos.longitude if has_pos else None,
                "bearing": _get(pos, "bearing") if has_pos else None,
                "speed": _get(pos, "speed") if has_pos else None,
                "odometer": _get(pos, "odometer") if has_pos else None,
                "current_stop_sequence": _get(vp, "current_stop_sequence"),
                "stop_id": _get(vp, "stop_id"),
                "current_status": _enum(vp, "current_status"),
                "vehicle_ts": _get(vp, "timestamp"),
                "congestion_level": _enum(vp, "congestion_level"),
                "occupancy_status": _enum(vp, "occupancy_status"),
            }
        )
    return rows


def trip_update_rows(feed, fetch_ts: int) -> list[dict]:
    """One row per stop_time_update.

    A trip update with no stop_time_updates (for example a canceled trip)
    still gets one row, with the stop columns set to None, so it is not lost.
    """
    header_ts = _get(feed.header, "timestamp")
    rows = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        base = {
            "fetch_ts_utc": fetch_ts,
            "feed_header_ts": header_ts,
            "entity_id": entity.id,
            **_trip_fields(tu.trip),
            "vehicle_id": _get(tu.vehicle, "id"),
            "trip_update_ts": _get(tu, "timestamp"),
            "trip_delay": _get(tu, "delay"),
        }
        if not tu.stop_time_update:
            rows.append(base)
            continue
        for stu in tu.stop_time_update:
            has_arr = stu.HasField("arrival")
            has_dep = stu.HasField("departure")
            rows.append(
                {
                    **base,
                    "stop_sequence": _get(stu, "stop_sequence"),
                    "stop_id": _get(stu, "stop_id"),
                    "arrival_time": _get(stu.arrival, "time") if has_arr else None,
                    "arrival_delay": _get(stu.arrival, "delay") if has_arr else None,
                    "departure_time": _get(stu.departure, "time") if has_dep else None,
                    "departure_delay": _get(stu.departure, "delay") if has_dep else None,
                    "stu_schedule_relationship": _enum(stu, "schedule_relationship"),
                }
            )
    return rows


# Feed name -> (row builder, schema). Used by main.py and reparse.
PARSERS = {
    "vehicle_positions": (vehicle_position_rows, VEHICLE_POSITIONS_SCHEMA),
    "trip_updates": (trip_update_rows, TRIP_UPDATES_SCHEMA),
}
