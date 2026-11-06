"""Build the small committed sample in data/sample/ that CI runs the pipeline on.

    .venv/bin/python scripts/make_sample.py

Takes one hour of real collected data (11:00 AM to 12:00 PM, 2026-11-06) for three
routes, and every ping from the vehicles that served them in that hour, so the
layover logic has its before- and after-trip pings. The static GTFS is cut down to
those routes. The layout matches data/ so dbt runs on it with --vars data_dir.

Those vehicles also ran trips on other routes, which are not in the cut-down static
GTFS. dbt's referential integrity tests (severity warn) report them as warnings on
the sample. That is expected and shows the tests working.
"""

import csv
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data"
OUT = ROOT / "data" / "sample"
DATE = "2026-11-06"
ROUTES = ["C53", "D60", "A58"]
START = "2026-11-06 11:00:00-05:00"
END = "2026-11-06 12:00:00-05:00"


def main() -> None:
    for sub in ["parsed", "static", "logs"]:
        shutil.rmtree(OUT / sub, ignore_errors=True)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'America/New_York'")
    window = f"fetch_ts_utc >= epoch(timestamptz '{START}') and fetch_ts_utc < epoch(timestamptz '{END}')"
    routes = ", ".join(f"'{r}'" for r in ROUTES)

    vp = f"read_parquet('{SRC}/parsed/vehicle_positions/date={DATE}/*.parquet')"
    tu = f"read_parquet('{SRC}/parsed/trip_updates/date={DATE}/*.parquet')"
    con.execute(f"""
        create table vehicles as
        select distinct vehicle_id from {vp} where {window} and route_id in ({routes})
    """)
    for feed, src, keep in [
        ("vehicle_positions", vp, "vehicle_id in (select vehicle_id from vehicles)"),
        ("trip_updates", tu, f"route_id in ({routes})"),
    ]:
        path = OUT / "parsed" / feed / f"date={DATE}" / "sample.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY (SELECT * FROM {src} WHERE {window} AND {keep} ORDER BY ALL) TO '{path}'"
        )
        print(
            f"{feed}: {con.execute('SELECT count(*) FROM read_parquet(?)', [str(path)]).fetchone()[0]} rows"
        )

    # Static GTFS: the version for DATE, cut to the sample routes.
    with (SRC / "static" / "feed_versions.csv").open() as f:
        version = next(r["feed_version"] for r in csv.DictReader(f) if r["collection_date"] == DATE)
    src_static = SRC / "static" / version
    out_static = OUT / "static" / version
    out_static.mkdir(parents=True)
    s = lambda name: f"read_parquet('{src_static}/{name}.parquet')"  # noqa: E731
    con.execute(f"create table trips as select * from {s('trips')} where route_id in ({routes})")
    subsets = {
        "routes": f"select * from {s('routes')} where route_id in ({routes})",
        "trips": "select * from trips",
        "stop_times": f"select * from {s('stop_times')} where trip_id in (select trip_id from trips)",
        "shapes": f"select * from {s('shapes')} where shape_id in (select shape_id from trips)",
        "calendar": f"select * from {s('calendar')}",
        "calendar_dates": f"select * from {s('calendar_dates')}",
        "agency": f"select * from {s('agency')}",
        "feed_info": f"select * from {s('feed_info')}",
    }
    for name, sql in subsets.items():
        con.execute(f"COPY ({sql}) TO '{out_static / (name + '.parquet')}'")
    # Stops: every stop the sample trips use, plus stops the sample pings report.
    con.execute(f"""
        COPY (
            select * from {s("stops")}
            where stop_id in (select stop_id from read_parquet('{out_static}/stop_times.parquet'))
               or stop_id in (select stop_id from read_parquet('{OUT}/parsed/vehicle_positions/*/*.parquet'))
        ) TO '{out_static / "stops.parquet"}'
    """)
    (out_static / "_complete").write_text("")
    (OUT / "static" / "feed_versions.csv").write_text(
        f"collection_date,feed_version\n{DATE},{version}\n"
    )

    # Collector log for the same hour.
    (OUT / "logs").mkdir()
    con.execute(f"""
        COPY (
            select * from read_csv('{SRC}/logs/fetches.csv', header = true, all_varchar = true)
            where cast(fetch_ts_utc as bigint) >= epoch(timestamptz '{START}')
              and cast(fetch_ts_utc as bigint) < epoch(timestamptz '{END}')
            order by fetch_ts_utc, feed
        ) TO '{OUT / "logs" / "fetches.csv"}' (HEADER)
    """)
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"sample size: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
