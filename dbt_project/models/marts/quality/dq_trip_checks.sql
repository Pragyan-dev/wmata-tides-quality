-- One row per performed trip with trip-level quality measures and flags.
--   too_few_pings       fewer than dq_min_pings_per_trip on-route pings
--   has_coverage_gap    two consecutive pings on the trip more than dq_coverage_gap_s apart
--   overlaps_feed_gap   the trip was running while the collector missed polls
--   cut_by_window       the trip was scheduled to start before or end after the collected window
--   is_complete         every timepoint on the trip has an inferred time

with ping_stats as (
    select
        p.service_date,
        p.trip_id,
        p.vehicle_id,
        count(*) as n_pings,
        count(*) filter (where s.is_on_route) as n_on_route_pings,
        count(*) filter (where p.impossible_speed) as n_impossible_speed,
        count(*) filter (where p.stale_ping) as n_stale,
        min(p.event_ts) as first_ping_ts,
        max(p.event_ts) as last_ping_ts
    from {{ ref('dq_ping_checks') }} p
    left join {{ ref('int_pings_snapped') }} s
        on s.location_ping_id = p.location_ping_id and s.ping_source = 'own_trip'
    where p.trip_id is not null
    group by p.service_date, p.trip_id, p.vehicle_id
),

gaps as (
    select
        service_date,
        trip_id,
        vehicle_id,
        max(event_epoch - prev_epoch) as max_ping_gap_s
    from (
        select
            service_date, trip_id, vehicle_id, event_epoch,
            lag(event_epoch) over (
                partition by service_date, trip_id, vehicle_id order by event_epoch
            ) as prev_epoch
        from {{ ref('stg_rt__vehicle_positions') }}
        where trip_id is not null
    )
    group by service_date, trip_id, vehicle_id
),

visit_stats as (
    select
        service_date,
        trip_id_performed,
        count(*) as n_scheduled_stops,
        count(*) filter (where schedule_relationship = 'Scheduled') as n_inferred_stops,
        count(*) filter (where timepoint) as n_timepoints,
        count(*) filter (where timepoint and schedule_relationship = 'Scheduled')
            as n_inferred_timepoints,
        max(interpolation_gap_s) filter (where timepoint) as max_timepoint_gap_s
    from {{ ref('stop_visits') }}
    group by service_date, trip_id_performed
),

feed_gaps as (
    select
        fetched_at as gap_end,
        fetched_at - to_seconds(seconds_since_prev_fetch) as gap_start
    from {{ ref('dq_feed_checks') }}
    where feed = 'vehicle_positions' and missed_polls > 0
),

collected as (
    select min(fetched_at) as window_start, max(fetched_at) as window_end
    from {{ ref('stg_collector__fetches') }}
    where feed = 'vehicle_positions' and http_status = 200
)

select
    t.service_date,
    t.trip_id_performed,
    t.trip_id_scheduled,
    t.vehicle_id,
    t.route_id,
    t.direction_id,
    t.schedule_trip_start,
    t.schedule_trip_end,
    hour(t.schedule_trip_start) as scheduled_start_hour,
    ps.n_pings,
    ps.n_on_route_pings,
    round(100.0 * (ps.n_pings - ps.n_on_route_pings) / ps.n_pings, 1) as pct_off_route,
    ps.n_impossible_speed,
    ps.n_stale,
    g.max_ping_gap_s,
    v.n_scheduled_stops,
    v.n_inferred_stops,
    v.n_timepoints,
    v.n_inferred_timepoints,
    v.max_timepoint_gap_s,
    ps.n_on_route_pings < {{ var('dq_min_pings_per_trip') }} as too_few_pings,
    coalesce(g.max_ping_gap_s > {{ var('dq_coverage_gap_s') }}, false) as has_coverage_gap,
    exists (
        select 1 from feed_gaps f
        where f.gap_start < coalesce(t.schedule_trip_end, ps.last_ping_ts)
          and f.gap_end > coalesce(t.schedule_trip_start, ps.first_ping_ts)
    ) as overlaps_feed_gap,
    coalesce(
        t.schedule_trip_start < c.window_start or t.schedule_trip_end > c.window_end,
        true
    ) as cut_by_window,
    coalesce(v.n_timepoints > 0 and v.n_inferred_timepoints = v.n_timepoints, false)
        as is_complete,
    t.is_in_static_gtfs
from {{ ref('trips_performed') }} t
cross join collected c
left join ping_stats ps
    on ps.service_date = t.service_date
    and ps.trip_id = t.trip_id_scheduled
    and ps.vehicle_id = t.vehicle_id
left join gaps g
    on g.service_date = t.service_date
    and g.trip_id = t.trip_id_scheduled
    and g.vehicle_id = t.vehicle_id
left join visit_stats v
    on v.service_date = t.service_date and v.trip_id_performed = t.trip_id_performed
