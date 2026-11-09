"""Dagster wiring. Needs dbt_project/target/manifest.json (run `dbt parse` first; CI does)."""

import dagster as dg

from orchestration.definitions import daily, defs

COLLECTOR_OUTPUTS = {
    dg.AssetKey(["collected", name]) for name in ["vehicle_positions", "trip_updates", "fetch_log"]
}


def test_definitions_load():
    defs.validate_loadable(defs)


def test_every_dependency_is_a_real_asset():
    # A misspelled dependency becomes an unbuildable placeholder and the step runs too
    # early. Only the collector's own outputs may be unbuilt by Dagster.
    graph = defs.resolve_asset_graph()
    unbuilt = {k for k in graph.get_all_asset_keys() if not graph.get(k).is_materializable}
    assert unbuilt == COLLECTOR_OUTPUTS


def test_exports_run_after_dbt():
    graph = defs.resolve_asset_graph()
    tides_parents = graph.get(dg.AssetKey("tides_package")).parent_keys
    assert dg.AssetKey(["tides", "stop_visits"]) in tides_parents
    extract_parents = graph.get(dg.AssetKey("dashboard_extracts")).parent_keys
    assert dg.AssetKey("tides_package") in extract_parents
    assert dg.AssetKey(["metrics", "timepoint_events"]) in extract_parents


def test_partition_is_3am_to_3am_new_york():
    window = daily.time_window_for_partition_key("2026-11-06")
    assert window.start.isoformat() == "2026-11-06T03:00:00-05:00"
    assert window.end.isoformat() == "2026-11-07T03:00:00-05:00"


def test_partitions_follow_dst():
    # 2027-03-14 springs forward, so the partition that spans it is 23 hours long.
    window = daily.time_window_for_partition_key("2027-03-13")
    assert window.start.isoformat() == "2027-03-13T03:00:00-05:00"
    assert window.end.isoformat() == "2027-03-14T03:00:00-04:00"
    assert window.end.timestamp() - window.start.timestamp() == 23 * 3600


def test_dbt_backfills_run_one_day_at_a_time():
    graph = defs.resolve_asset_graph()
    policy = graph.get(dg.AssetKey(["tides", "stop_visits"])).backfill_policy
    assert policy.max_partitions_per_run == 1
