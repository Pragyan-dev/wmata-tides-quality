-- One row per timepoint on every performed trip: the event WMATA's on-time
-- performance measures, with its deviation from schedule and the quality flags
-- the sensitivity analysis and the dashboard filter on.
--
-- WMATA measures departures from timepoints. At the last timepoint it measures the
-- arrival, and only lateness counts (Metrobus Service Guidelines).

with timepoints as (
    select
        v.service_date,
        v.trip_id_performed,
        v.trip_stop_sequence,
        v.stop_id,
        v.vehicle_id,
        v.schedule_relationship,
        v.interpolation_gap_s,
        v.arrival_method,
        v.departure_method,
        v.trip_stop_sequence = max(v.trip_stop_sequence) over (
            partition by v.service_date, v.trip_id_performed
        ) as is_last_timepoint,
        v.schedule_departure_time,
        v.schedule_arrival_time,
        v.actual_departure_time,
        v.actual_arrival_time
    from {{ ref('stop_visits') }} v
    where v.timepoint
),

events as (
    select
        tp.service_date,
        tp.trip_id_performed,
        tc.trip_id_scheduled,
        tc.route_id,
        tc.direction_id,
        tp.trip_stop_sequence,
        tp.stop_id,
        tp.vehicle_id,
        tp.is_last_timepoint,
        case when tp.is_last_timepoint then 'arrival' else 'departure' end as measured_event,
        case when tp.is_last_timepoint then tp.schedule_arrival_time
             else tp.schedule_departure_time end as scheduled_ts,
        case when tp.is_last_timepoint then tp.actual_arrival_time
             else tp.actual_departure_time end as actual_ts,
        case when tp.is_last_timepoint then tp.arrival_method
             else tp.departure_method end as time_method,
        tp.interpolation_gap_s,
        tc.pct_off_route,
        tc.n_impossible_speed,
        tc.n_stale,
        tc.too_few_pings,
        tc.has_coverage_gap,
        tc.overlaps_feed_gap,
        tc.cut_by_window,
        tc.is_complete
    from timepoints tp
    join {{ ref('dq_trip_checks') }} tc using (service_date, trip_id_performed)
),

with_deviation as (
    select
        *,
        hour(scheduled_ts) as scheduled_hour,
        epoch(actual_ts) - epoch(scheduled_ts) as deviation_s
    from events
)

select
    *,
    case when actual_ts is not null then {{ is_on_time('deviation_s', 'is_last_timepoint') }} end
        as is_on_time,
    case when actual_ts is not null then {{ is_early('deviation_s', 'is_last_timepoint') }} end
        as is_early,
    case when actual_ts is not null then {{ is_late('deviation_s') }} end as is_late,
    actual_ts is not null and {{ passes_filter('moderate') }} as passes_moderate,
    actual_ts is not null and {{ passes_filter('strict') }} as passes_strict
from with_deviation
