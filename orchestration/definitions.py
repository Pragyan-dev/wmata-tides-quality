"""Dagster definitions for the daily batch.

The collector keeps running on its own (it is a 30-second loop, not a batch job).
Dagster builds everything after it, one partition per service day:

    collection_coverage   how many of the day's polls the collector actually made
    static_gtfs           unpack static GTFS versions to Parquet (collector load-static)
    dbt models            staging, intermediate, TIDES, quality, metrics (dbt build)
    tides_package         TIDES CSVs + datapackage.json, validated against TIDES v1.0
    dashboard_extracts    CSVs for Power BI or Tableau

A partition covers 3:00 AM to 3:00 AM America/New_York, so trips that run past
midnight stay with their service day. Each partition builds into its own DuckDB file,
data/daily/<date>/warehouse.duckdb, so days are independent and the snapshot used by
the docs (data/warehouse.duckdb) is never touched.

Run the UI with:  scripts/dagster.sh
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import dagster as dg
import duckdb
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from collector.load_static import load_static

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DBT_DIR = ROOT / "dbt_project"
MIN_COVERAGE_PCT = 95.0

daily = dg.DailyPartitionsDefinition(
    start_date="2026-11-06", timezone="America/New_York", hour_offset=3
)
# One day per run, for every asset: each run builds into that day's own DuckDB file.
ONE_DAY_PER_RUN = dg.BackfillPolicy.multi_run(max_partitions_per_run=1)


def _load_script(name: str):
    """Import a file from scripts/ so Dagster runs the same code as the command line."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def day_dir(context) -> Path:
    return DATA / "daily" / context.partition_key


def day_db(context) -> Path:
    return day_dir(context) / "warehouse.duckdb"


# ---------------------------------------------------------------- collector side

collected_feeds = [
    dg.AssetSpec(
        key=["collected", name],
        description=description,
        group_name="collector",
        kinds={"python"},
    )
    for name, description in [
        ("vehicle_positions", "Parsed VehiclePositions Parquet, written by the collector."),
        ("trip_updates", "Parsed TripUpdates Parquet, written by the collector."),
        ("fetch_log", "data/logs/fetches.csv, one line per fetch, written by the collector."),
    ]
]


@dg.asset(
    partitions_def=daily,
    backfill_policy=ONE_DAY_PER_RUN,
    group_name="collector",
    deps=[["collected", "fetch_log"]],
    check_specs=[
        dg.AssetCheckSpec(
            "coverage_at_least_95_pct",
            asset="collection_coverage",
            description="Warns when the collector made under 95% of the day's polls.",
        )
    ],
    kinds={"duckdb"},
)
def collection_coverage(context: dg.AssetExecutionContext):
    """Share of the day's expected 30-second polls that succeeded, per feed."""
    window = context.partition_time_window
    # Real elapsed seconds. Subtracting the datetimes directly gives wall-clock time,
    # which is wrong on DST change days (23 or 25 hours).
    expected = int((window.end.timestamp() - window.start.timestamp()) // 30)
    con = duckdb.connect()
    rows = con.execute(
        """
        select feed, count(*) filter (where http_status = '200') as ok
        from read_csv(?, header = true, all_varchar = true)
        where cast(fetch_ts_utc as bigint) >= ? and cast(fetch_ts_utc as bigint) < ?
          and feed in ('vehicle_positions', 'trip_updates')
        group by feed
        """,
        [str(DATA / "logs" / "fetches.csv"), window.start.timestamp(), window.end.timestamp()],
    ).fetchall()
    ok = {feed: n for feed, n in rows}
    coverage = {
        feed: round(100 * ok.get(feed, 0) / expected, 1)
        for feed in ["vehicle_positions", "trip_updates"]
    }
    lowest = min(coverage.values())
    return dg.MaterializeResult(
        metadata={
            "expected_polls": expected,
            "vehicle_positions_polls": ok.get("vehicle_positions", 0),
            "trip_updates_polls": ok.get("trip_updates", 0),
            "vehicle_positions_coverage_pct": coverage["vehicle_positions"],
            "trip_updates_coverage_pct": coverage["trip_updates"],
        },
        check_results=[
            dg.AssetCheckResult(
                check_name="coverage_at_least_95_pct",
                passed=lowest >= MIN_COVERAGE_PCT,
                severity=dg.AssetCheckSeverity.WARN,
                metadata={"lowest_coverage_pct": lowest},
                description=f"Lowest feed coverage {lowest}% (threshold {MIN_COVERAGE_PCT}%).",
            )
        ],
    )


GTFS_TABLES = [
    "routes",
    "trips",
    "stops",
    "stop_times",
    "shapes",
    "calendar",
    "calendar_dates",
    "feed_info",
    "feed_versions",
]


@dg.multi_asset(
    specs=[
        dg.AssetSpec(["static_gtfs", t], group_name="collector", kinds={"python", "parquet"})
        for t in GTFS_TABLES
    ],
    partitions_def=daily,
    backfill_policy=ONE_DAY_PER_RUN,
)
def static_gtfs(context: dg.AssetExecutionContext):
    """Unpack each distinct static GTFS version to Parquet (collector load-static).

    One Dagster asset per GTFS table, because each is a separate dbt source.
    """
    load_static()
    versions = (DATA / "static" / "feed_versions.csv").read_text().strip().splitlines()[1:]
    metadata = {
        "dates_mapped": len(versions),
        "distinct_versions": len({line.split(",")[1] for line in versions}),
    }
    for t in GTFS_TABLES:
        yield dg.MaterializeResult(asset_key=["static_gtfs", t], metadata=metadata)


# ---------------------------------------------------------------- dbt

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()


class Translator(DagsterDbtTranslator):
    """Point dbt sources at the Dagster assets that produce them."""

    def get_asset_key(self, dbt_resource_props):
        if dbt_resource_props["resource_type"] == "source":
            source, table = dbt_resource_props["source_name"], dbt_resource_props["name"]
            if source == "gtfs":
                return dg.AssetKey(["static_gtfs", table])
            if source == "collector":
                return dg.AssetKey(["collected", "fetch_log"])
            return dg.AssetKey(["collected", table])
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    partitions_def=daily,
    dagster_dbt_translator=Translator(),
    backfill_policy=ONE_DAY_PER_RUN,
)
def wmata_dbt(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    """dbt build for one service day, into that day's own DuckDB file."""
    window = context.partition_time_window
    db = day_db(context)
    db.parent.mkdir(parents=True, exist_ok=True)
    # Each step runs in its own process, so this only affects this dbt build.
    os.environ["WMATA_DUCKDB_PATH"] = str(db)
    dbt_vars = {
        "collected_after": window.start.isoformat(),
        "collected_before": window.end.isoformat(),
    }
    yield from dbt.cli(["build", "--vars", json.dumps(dbt_vars)], context=context).stream()


# ---------------------------------------------------------------- exports


@dg.asset(
    partitions_def=daily,
    backfill_policy=ONE_DAY_PER_RUN,
    group_name="exports",
    # dagster-dbt keys are <schema>/<model>.
    deps=[
        dg.AssetKey(["tides", t]) for t in ["vehicle_locations", "trips_performed", "stop_visits"]
    ],
    check_specs=[
        dg.AssetCheckSpec(
            "valid_against_tides_v1",
            asset="tides_package",
            blocking=True,
            description="datapackage.json and every table validate against TIDES v1.0.",
        )
    ],
    kinds={"csv"},
)
def tides_package(context: dg.AssetExecutionContext):
    """TIDES CSVs and datapackage.json for the day, in data/tides/<date>/."""
    export_tides = _load_script("export_tides")
    out_dir = DATA / "tides" / context.partition_key
    con = duckdb.connect(str(day_db(context)), read_only=True)
    con.execute("SET TimeZone = 'America/New_York'")
    counts = export_tides.export(con, out_dir, None)
    con.close()
    package = export_tides.write_datapackage(out_dir, context.partition_key, counts)
    results = export_tides.validate(out_dir, package)
    passed = all(r["valid"] for r in results.values())
    return dg.MaterializeResult(
        metadata={**{f"{t}_rows": n for t, n in counts.items()}, "path": str(out_dir)},
        check_results=[
            dg.AssetCheckResult(
                check_name="valid_against_tides_v1",
                passed=passed,
                metadata={
                    f"{name}_errors": sum(r["errors"].values()) for name, r in results.items()
                },
            )
        ],
    )


@dg.asset(
    partitions_def=daily,
    backfill_policy=ONE_DAY_PER_RUN,
    group_name="exports",
    deps=[
        tides_package,
        *[
            dg.AssetKey(["metrics", t])
            for t in [
                "timepoint_events",
                "headways",
                "dim_routes",
                "dim_stops",
                "otp_by_route",
                "otp_by_stop",
                "otp_by_hour",
                "otp_by_route_hour",
                "headway_by_route",
            ]
        ],
        *[
            dg.AssetKey(["quality", t])
            for t in [
                "data_quality",
                "dq_otp_sensitivity",
                "dq_otp_filter_effects",
                "dq_otp_sensitivity_by_route",
            ]
        ],
    ],
    kinds={"csv"},
)
def dashboard_extracts(context: dg.AssetExecutionContext):
    """CSVs for Power BI or Tableau, in data/powerbi/<date>/."""
    out = DATA / "powerbi" / context.partition_key
    counts = _load_script("export_powerbi").export_all(str(day_db(context)), out)
    return dg.MaterializeResult(
        metadata={**{f"{n}_rows": r for n, r in counts.items()}, "path": str(out)}
    )


# ---------------------------------------------------------------- job and schedule

# Everything Dagster builds. The collected_* assets are produced by the collector itself.
daily_pipeline = dg.define_asset_job(
    "daily_pipeline",
    selection=dg.AssetSelection.assets(
        collection_coverage, static_gtfs, wmata_dbt, tides_package, dashboard_extracts
    ),
)

# Runs at 4:00 AM for the day that ended at 3:00 AM.
daily_schedule = dg.build_schedule_from_partitioned_job(
    daily_pipeline, hour_of_day=4, minute_of_hour=0
)

defs = dg.Definitions(
    assets=[
        *collected_feeds,
        collection_coverage,
        static_gtfs,
        wmata_dbt,
        tides_package,
        dashboard_extracts,
    ],
    jobs=[daily_pipeline],
    schedules=[daily_schedule],
    resources={
        # Use the dbt installed next to the Python running Dagster (the project's .venv).
        "dbt": DbtCliResource(
            project_dir=dbt_project, dbt_executable=str(Path(sys.executable).parent / "dbt")
        )
    },
)
