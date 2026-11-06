"""Compare this pipeline's TIDES output with evansiroky/gtfs-rt-to-tides on the same raw files.

Run after scripts/build_snapshot.sh and after running gtfs-rt-to-tides into
data/compare/their_output (see docs/DATA_QUALITY.md, section 5, for the exact commands).

    .venv/bin/python scripts/compare_gtfs_rt_to_tides.py

Prints every number used in the comparison section of docs/DATA_QUALITY.md.
"""

import json
from pathlib import Path

import duckdb
from frictionless import Detector, Resource, Schema

ROOT = Path(__file__).resolve().parent.parent
THEIRS = ROOT / "data" / "compare" / "their_output"
SPEC = ROOT / "spec" / "tides-v1.0"


def show(con, title: str, sql: str) -> None:
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    rows = rel.fetchall()
    print(f"\n## {title}\n")
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for row in rows:
        print("| " + " | ".join("" if v is None else str(v) for v in row) + " |")


def validate_theirs() -> None:
    """Header differences first, then value errors with columns matched by name."""
    print("\n## Their files against TIDES v1.0 schemas\n")
    for name in ["vehicle_locations", "trips_performed"]:
        descriptor = json.loads((SPEC / f"{name}.schema.json").read_text())
        folder = THEIRS / "2026-11-06"
        header = (folder / f"{name}.csv").open().readline().strip().split(",")
        fields = [f["name"] for f in descriptor["fields"]]
        required = [
            f["name"] for f in descriptor["fields"] if f.get("constraints", {}).get("required")
        ]
        print(f"- {name}")
        print(f"  - columns not in the TIDES schema: {[c for c in header if c not in fields]}")
        print(f"  - required TIDES fields missing: {[f for f in required if f not in header]}")
        resource = Resource(
            path=f"{name}.csv",
            basepath=str(folder),
            schema=Schema.from_descriptor(descriptor),
            detector=Detector(schema_sync=True),
        )
        task = resource.validate(limit_errors=1_000_000).tasks[0]
        by_field: dict[str, int] = {}
        for error in task.errors:
            key = f"{error.type} on {getattr(error, 'field_name', '') or 'row'}"
            by_field[key] = by_field.get(key, 0) + 1
        print(f"  - value errors by field (columns matched by name): {by_field or 'none'}")


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    con.execute("SET TimeZone = 'America/New_York'")
    vl = THEIRS / "2026-11-06" / "vehicle_locations.csv"
    tp = THEIRS / "2026-11-06" / "trips_performed.csv"
    con.execute(f"CREATE TEMP VIEW their_vl AS SELECT * FROM read_csv('{vl}', all_varchar=true)")
    con.execute(f"CREATE TEMP VIEW their_tp AS SELECT * FROM read_csv('{tp}', all_varchar=true)")
    con.execute(
        "CREATE TEMP VIEW their_tp_unmodified AS SELECT * FROM "
        f"read_csv('{THEIRS / 'trips_performed_unmodified.csv'}', all_varchar=true)"
    )

    validate_theirs()

    show(
        con,
        "Row counts",
        """
        select 'vehicle_locations' as table_name,
               (select count(*) from tides.vehicle_locations) as ours,
               (select count(*) from their_vl) as theirs
        union all
        select 'trips_performed',
               (select count(*) from tides.trips_performed),
               (select count(*) from their_tp)
        union all
        select 'trips_performed, excluding their Missing rows',
               (select count(*) from tides.trips_performed),
               (select count(*) from their_tp where schedule_relationship <> 'Missing')
    """,
    )

    # Match pings on vehicle and timestamp. Their ID also embeds position, bearing, speed.
    con.execute("""
        CREATE TEMP TABLE matched AS
        SELECT o.*, t.service_date AS t_service_date, t.trip_id_performed AS t_trip,
               t.current_status AS t_status, t.heading AS t_heading, t.speed AS t_speed,
               t.latitude AS t_lat, t.longitude AS t_lon,
               t.schedule_relationship AS t_rel, t.event_timestamp AS t_ts
        FROM tides.vehicle_locations o
        JOIN their_vl t
          ON t.vehicle_id = o.vehicle_id
         AND epoch(cast(t.event_timestamp AS timestamptz)) = epoch(o.event_timestamp)
    """)
    show(
        con,
        "vehicle_locations: field agreement on matched pings",
        """
        select
            count(*) as matched_pings,
            count(*) filter (where abs(cast(t_lat as double) - latitude) < 1e-9
                               and abs(cast(t_lon as double) - longitude) < 1e-9) as same_position,
            count(*) filter (where coalesce(t_trip, '') = coalesce(trip_id_scheduled, ''))
                as same_trip_id,
            count(*) filter (where trip_id_scheduled is null and t_service_date is null)
                as no_trip_and_their_service_date_empty,
            count(*) filter (where heading is null and cast(t_heading as double) = 0)
                as our_heading_null_theirs_0,
            count(*) filter (where speed is null and cast(t_speed as double) = 0)
                as our_speed_null_theirs_0
        from matched
    """,
    )
    show(
        con,
        "vehicle_locations: current_status values",
        """
        select t_status as theirs, current_status as ours, count(*) as pings
        from matched group by all order by pings desc
    """,
    )
    show(
        con,
        "vehicle_locations: schedule_relationship values",
        """
        select t_rel as theirs, schedule_relationship as ours, count(*) as pings
        from matched group by all order by pings desc
    """,
    )

    show(
        con,
        "trips_performed: their schedule_relationship values",
        """
        select schedule_relationship, count(*) as trips,
               count(*) filter (where vehicle_id is null) as no_vehicle_id
        from their_tp group by all order by trips desc
    """,
    )
    show(
        con,
        "trips_performed: unmodified run vs patched run",
        """
        select 'unmodified' as run,
               count(*) filter (where schedule_relationship <> 'Missing') as observed
        from their_tp_unmodified
        union all
        select 'patched', count(*) filter (where schedule_relationship <> 'Missing') from their_tp
    """,
    )
    show(
        con,
        "trips_performed: trips run by more than one vehicle (ours)",
        """
        select count(*) as trips_with_2plus_vehicles from (
            select trip_id_scheduled from tides.trips_performed
            group by trip_id_scheduled having count(*) > 1)
    """,
    )

    # Actual start and end: theirs come from the TripUpdates time at the lowest and highest
    # stop_sequence seen; ours are inferred from VehiclePositions.
    con.execute("""
        CREATE TEMP TABLE trip_times AS
        SELECT o.trip_id_scheduled,
               o.actual_trip_start AS our_start, o.actual_trip_end AS our_end,
               o.trip_start_stop_id AS our_start_stop, o.trip_end_stop_id AS our_end_stop,
               cast(nullif(t.actual_trip_start, '') AS timestamptz) AS their_start,
               cast(nullif(t.actual_trip_end, '') AS timestamptz) AS their_end,
               t.trip_start_stop_id AS their_start_stop, t.trip_end_stop_id AS their_end_stop
        FROM (select * from tides.trips_performed
              qualify count(*) over (partition by trip_id_scheduled) = 1) o
        JOIN their_tp t ON t.trip_id_scheduled = o.trip_id_scheduled
        WHERE t.schedule_relationship <> 'Missing'
    """)
    show(
        con,
        "trips_performed: actual start and end",
        """
        select
            count(*) as trips_compared,
            count(*) filter (where their_start_stop = our_start_stop) as same_start_stop,
            count(*) filter (where their_end_stop = our_end_stop) as same_end_stop,
            count(*) filter (where our_start is not null and their_start is not null
                               and their_start_stop = our_start_stop) as start_both,
            round(median(abs(epoch(their_start - our_start))) filter (
                where their_start_stop = our_start_stop), 1) as median_abs_start_diff_s,
            round(quantile_cont(abs(epoch(their_start - our_start)), 0.9) filter (
                where their_start_stop = our_start_stop), 1) as p90_abs_start_diff_s,
            count(*) filter (where our_end is not null and their_end is not null
                               and their_end_stop = our_end_stop) as end_both,
            round(median(abs(epoch(their_end - our_end))) filter (
                where their_end_stop = our_end_stop), 1) as median_abs_end_diff_s,
            round(quantile_cont(abs(epoch(their_end - our_end)), 0.9) filter (
                where their_end_stop = our_end_stop), 1) as p90_abs_end_diff_s,
            count(*) filter (where year(their_start) < 2000 or year(their_end) < 2000)
                as their_epoch_zero_times
        from trip_times
    """,
    )


if __name__ == "__main__":
    main()
