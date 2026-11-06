-- Every quality check summarized by day and route: how many rows were checked and
-- how many were flagged. Feed-level checks have route_id = 'ALL'.
-- One table to read for "how good was the data on route X on day Y".

with ping_flags as (
    unpivot (
        select
            service_date,
            coalesce(route_id, '(no trip)') as route_id,
            missing_position::int as missing_position,
            outside_service_area::int as outside_service_area,
            impossible_speed::int as impossible_speed,
            stale_ping::int as stale_ping,
            off_route::int as off_route,
            trip_not_in_static::int as trip_not_in_static,
            stop_not_in_static::int as stop_not_in_static
        from {{ ref('dq_ping_checks') }}
    )
    on missing_position, outside_service_area, impossible_speed, stale_ping, off_route,
       trip_not_in_static, stop_not_in_static
    into name check_name value flagged
),

trip_flags as (
    unpivot (
        select
            service_date,
            route_id,
            too_few_pings::int as too_few_pings,
            has_coverage_gap::int as coverage_gap,
            overlaps_feed_gap::int as overlaps_feed_gap,
            cut_by_window::int as cut_by_window,
            (not is_complete)::int as incomplete_timepoints,
            (n_impossible_speed > 0)::int as trip_has_impossible_speed,
            (n_stale > 0)::int as trip_has_stale_ping
        from {{ ref('dq_trip_checks') }}
    )
    on too_few_pings, coverage_gap, overlaps_feed_gap, cut_by_window, incomplete_timepoints,
       trip_has_impossible_speed, trip_has_stale_ping
    into name check_name value flagged
),

stop_flags as (
    select
        v.service_date,
        t.route_id,
        'no_inferred_visit' as check_name,
        (v.schedule_relationship <> 'Scheduled')::int as flagged
    from {{ ref('stop_visits') }} v
    join {{ ref('trips_performed') }} t using (service_date, trip_id_performed)
    union all
    select
        v.service_date,
        t.route_id,
        'timepoint_no_inferred_visit',
        (v.schedule_relationship <> 'Scheduled')::int
    from {{ ref('stop_visits') }} v
    join {{ ref('trips_performed') }} t using (service_date, trip_id_performed)
    where v.timepoint
),

feed_flags as (
    unpivot (
        select
            fetch_date as service_date,
            'ALL' as route_id,
            feed,
            failed_fetch::int as failed_fetch,
            empty_feed::int as empty_feed,
            stale_feed::int as stale_feed,
            (missed_polls > 0)::int as missed_polls
        from {{ ref('dq_feed_checks') }}
    )
    on failed_fetch, empty_feed, stale_feed, missed_polls
    into name check_name value flagged
),

unobserved_flags as (
    select service_date, route_id, 'scheduled_trip_not_observed' as check_name,
           (not was_observed)::int as flagged
    from {{ ref('dq_unobserved_trips') }}
),

all_flags as (
    select service_date, route_id, 'ping' as check_level, check_name, flagged from ping_flags
    union all
    select service_date, route_id, 'trip', check_name, flagged from trip_flags
    union all
    select service_date, route_id, 'stop_visit', check_name, flagged from stop_flags
    union all
    select service_date, route_id, 'trip', check_name, flagged from unobserved_flags
    union all
    select service_date, route_id, 'feed', feed || ':' || check_name, flagged from feed_flags
)

select
    service_date,
    route_id,
    check_level,
    check_name,
    count(*) as n_checked,
    sum(flagged) as n_flagged,
    round(100.0 * sum(flagged) / count(*), 2) as pct_flagged
from all_flags
group by service_date, route_id, check_level, check_name
