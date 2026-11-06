"""Print every number cited in docs/METHODOLOGY.md and docs/DATA_QUALITY.md.

Run after scripts/build_snapshot.sh:

    .venv/bin/python scripts/report.py > data/report.md

Each section prints one markdown table, so a number in the docs can be traced back
to the query that produced it.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent

QUERIES = {
    # ---------- window and staging
    "Window": """
        select count(*) as pings, count(distinct vehicle_id) as vehicles,
               round(100.0 * avg((trip_id is not null)::int), 1) as pct_on_trip,
               min(first_fetched_at)::varchar as first_fetch, max(first_fetched_at)::varchar as last_fetch
        from staging.stg_rt__vehicle_positions""",
    "Pings by number of fetches that carried them": """
        select least(times_seen, 5) as times_seen_capped_at_5, count(*) as pings,
               round(100.0 * count(*) / sum(count(*)) over (), 2) as pct
        from staging.stg_rt__vehicle_positions group by 1 order by 1""",
    "Ping age when first fetched (seconds)": """
        select quantile_cont(ping_age_s, [0.5, 0.9, 0.99, 0.999]) as p50_p90_p99_p999
        from staging.stg_rt__vehicle_positions""",
    "Occupancy status": """
        select occupancy_status, count(*) as pings,
               round(100.0 * count(*) / sum(count(*)) over (), 1) as pct
        from staging.stg_rt__vehicle_positions group by 1 order by 2 desc""",
    # ---------- inference
    "Stops placed on shapes": """
        select count(*) as shape_stops, round(100.0 * avg(is_out_of_order::int), 2) as pct_out_of_order,
               quantile_cont(stop_snap_distance_m, [0.5, 0.9, 0.99]) as snap_m_p50_p90_p99
        from intermediate.int_shape_stop_distances""",
    "Pings snapped, by source": """
        select ping_source, count(*) as pings, round(100.0 * avg(is_on_route::int), 1) as pct_on_route,
               quantile_cont(snap_distance_m, [0.5, 0.9, 0.99]) as snap_m_p50_p90_p99,
               round(100.0 * avg((abs(along_m - along_pass1_m) > 1)::int) filter (where is_on_route), 2)
                   as pct_pass2_changed,
               round(100.0 * avg((progress_m - along_m > 1)::int) filter (where is_on_route), 2)
                   as pct_progress_ahead
        from intermediate.int_pings_snapped group by 1 order by 1""",
    "Stop visits by outcome": """
        select coalesce(no_visit_reason, 'inferred') as outcome, schedule_relationship,
               count(*) as visits, round(100.0 * count(*) / sum(count(*)) over (), 2) as pct
        from tides.stop_visits group by all order by visits desc""",
    "Stop visits total": """
        select count(*) as visits, count(distinct trip_id_performed) as trips from tides.stop_visits""",
    "Departure method at first stops (timepoints on trips inside the window, no missed polls)": """
        select coalesce(v.departure_method, 'none') as method, coalesce(v.no_visit_reason, '-') as reason,
               count(*) as first_stops
        from tides.stop_visits v join quality.dq_trip_checks t using (service_date, trip_id_performed)
        where v.is_first_stop and v.timepoint and not t.cut_by_window and not t.overlaps_feed_gap
        group by all order by 3 desc""",
    "Arrival at last stops (same trips)": """
        select coalesce(v.arrival_method, 'none') as method, coalesce(v.no_visit_reason, '-') as reason,
               count(*) as last_stops
        from tides.stop_visits v join quality.dq_trip_checks t using (service_date, trip_id_performed)
        where v.is_last_stop and v.timepoint and not t.cut_by_window and not t.overlaps_feed_gap
        group by all order by 3 desc""",
    "Feed STOPPED_AT reports at a trip's last stop": """
        select count(*) filter (where p.current_stop_sequence = s.last_seq) as pings_targeting_last_stop,
               count(*) filter (where p.current_stop_sequence = s.last_seq
                                  and p.current_status = 'STOPPED_AT') as stopped_at_last_stop
        from staging.stg_rt__vehicle_positions p
        join (select service_date, trip_id, vehicle_id, max(stop_sequence) as last_seq
              from intermediate.int_stop_visits_inferred group by all) s
          using (service_date, trip_id, vehicle_id)""",
    "First-stop fallback vs shape method where both exist (seconds, fallback minus shape)": """
        with fb as (
            select p.service_date, p.trip_id, p.vehicle_id,
                   max(p.event_epoch) filter (where p.current_stop_sequence <= f.first_seq) as a,
                   min(p.event_epoch) filter (where p.current_stop_sequence > f.first_seq) as b
            from staging.stg_rt__vehicle_positions p
            join (select service_date, trip_id, vehicle_id, min(stop_sequence) as first_seq
                  from intermediate.int_stop_visits_inferred group by all) f
              using (service_date, trip_id, vehicle_id)
            group by all)
        select count(*) as trips,
               quantile_cont((fb.a + fb.b) / 2.0 - epoch(i.actual_departure_ts), [0.1, 0.25, 0.5, 0.75, 0.9])
                   as p10_p25_p50_p75_p90_fallback_minus_shape
        from intermediate.int_stop_visits_inferred i join fb using (service_date, trip_id, vehicle_id)
        where i.is_first_stop and i.departure_method = 'shape' and fb.a < fb.b""",
    "Interpolation gap of inferred visits (seconds)": """
        select quantile_cont(interpolation_gap_s, [0.5, 0.75, 0.9, 0.95, 0.99]) as p50_p75_p90_p95_p99,
               round(100.0 * avg((interpolation_gap_s <= 60)::int), 1) as pct_le_60,
               round(100.0 * avg((interpolation_gap_s <= 120)::int), 1) as pct_le_120,
               round(100.0 * avg((interpolation_gap_s <= 300)::int), 1) as pct_le_300
        from tides.stop_visits where interpolation_gap_s is not null""",
    "Dwell at intermediate stops (seconds)": """
        select quantile_cont(dwell, [0.1, 0.5, 0.9, 0.99]) as p10_p50_p90_p99, count(*) as visits
        from tides.stop_visits where dwell is not null""",
    "Consistency with feed STOPPED_AT pings": """
        with stopped as (
            select service_date, trip_id_performed, trip_stop_sequence, stop_id, event_timestamp as t
            from tides.vehicle_locations
            where current_status = 'Stopped at' and trip_id_performed is not null),
        j as (
            select s.t, v.actual_arrival_time as a, v.actual_departure_time as d
            from stopped s join tides.stop_visits v using (service_date, trip_id_performed, trip_stop_sequence)
            where v.stop_id = s.stop_id and v.actual_arrival_time is not null
              and v.actual_departure_time is not null),
        e as (select *, case when t < a then epoch(a - t) when t > d then epoch(t - d) else 0 end as err_s from j)
        select count(*) as pings, round(100.0 * avg((err_s = 0)::int), 1) as pct_inside,
               round(100.0 * avg((err_s <= 30)::int), 1) as pct_within_30s,
               round(100.0 * avg((err_s <= 60)::int), 1) as pct_within_60s,
               round(100.0 * avg((t < a)::int), 1) as pct_before_arrival,
               round(100.0 * avg((t > d)::int), 1) as pct_after_departure
        from e""",
    # ---------- data quality
    "Data quality checks, all routes": """
        select check_level, check_name, sum(n_checked) as checked, sum(n_flagged) as flagged,
               round(100.0 * sum(n_flagged) / sum(n_checked), 2) as pct
        from quality.data_quality group by all order by 1, 2""",
    "Missed polls": """
        select feed, sum(missed_polls) as missed_polls, count(*) filter (where missed_polls > 0) as gaps,
               max(seconds_since_prev_fetch) as longest_gap_s
        from quality.dq_feed_checks group by 1""",
    "Feed header age (seconds)": """
        select feed, quantile_cont(header_age_s, [0.5, 0.9, 0.99]) as p50_p90_p99, max(header_age_s) as max
        from quality.dq_feed_checks group by 1""",
    "Impossible-speed jumps": """
        select count(*) as pings, count(distinct vehicle_id) as vehicles,
               round(max(implied_speed_mps), 1) as max_mps, round(max(jump_m)) as max_jump_m
        from quality.dq_ping_checks where impossible_speed""",
    "Worst vehicles for impossible speed": """
        select vehicle_id, count(*) as jumps from quality.dq_ping_checks where impossible_speed
        group by 1 order by 2 desc limit 3""",
    "Routes with the highest off-route share (routes with 500+ trip pings)": """
        select route_id, sum(n_checked) as pings, round(100.0 * sum(n_flagged) / sum(n_checked), 1) as pct_off_route
        from quality.data_quality where check_name = 'off_route' and route_id <> '(no trip)'
        group by 1 having sum(n_checked) >= 500 order by 3 desc limit 5""",
    "Trips inside the window with no missed polls": """
        select count(*) as trips, count(*) filter (where is_complete) as complete,
               round(100.0 * avg(is_complete::int), 1) as pct_complete
        from quality.dq_trip_checks where not cut_by_window and not overlaps_feed_gap""",
    # ---------- sensitivity
    "OTP sensitivity": """
        select filter_level, timepoint_events, trips, routes, otp_pct, early_pct, late_pct,
               median_deviation_min, pct_of_loose_events, otp_change_vs_loose_pp
        from quality.dq_otp_sensitivity order by level_order""",
    "OTP filter effects (one filter at a time)": """
        select * from quality.dq_otp_filter_effects""",
    "OTP sensitivity by route (routes with 100+ loose and 30+ strict events)": """
        select count(*) as routes,
               quantile_cont(strict_minus_loose_pp, [0.1, 0.5, 0.9]) as p10_p50_p90_pp,
               min(strict_minus_loose_pp) as min_pp, max(strict_minus_loose_pp) as max_pp
        from quality.dq_otp_sensitivity_by_route where loose_events >= 100 and strict_events >= 30""",
    "Routes whose OTP moves most, strict vs loose (100+ loose and 30+ strict events)": """
        select route_id, loose_events, strict_events, loose_otp_pct, strict_otp_pct, strict_minus_loose_pp
        from quality.dq_otp_sensitivity_by_route where loose_events >= 100 and strict_events >= 30
        order by abs(strict_minus_loose_pp) desc limit 5""",
}


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    con.execute("SET TimeZone = 'America/New_York'")
    for title, sql in QUERIES.items():
        rel = con.execute(sql)
        cols = [d[0] for d in rel.description]
        print(f"\n## {title}\n")
        print("| " + " | ".join(cols) + " |")
        print("|" + "---|" * len(cols))
        for row in rel.fetchall():
            print("| " + " | ".join("" if v is None else str(v) for v in row) + " |")


if __name__ == "__main__":
    main()
