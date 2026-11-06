-- One row per pair of consecutive scheduled trips at a timepoint: the bus and the bus
-- scheduled just before it on the same route, direction, and stop.
--
-- Pairs come from the full schedule (int_scheduled_trips), so an unobserved trip does
-- not make the next headway look twice as long. Headways are measured only when both
-- buses have an inferred departure that passes the metrics quality level.
--
--   is_bunched          actual headway under bunching_threshold_s (negative means the
--                       later-scheduled bus left first)
--   headway_limit_s     WMATA rule: scheduled headway plus 15%, rounded up to a minute
--   is_headway_on_time  actual headway at or under headway_limit_s
--   is_frequent         scheduled headway of 12 minutes or less

with scheduled as (
    select
        s.service_date,
        s.route_id,
        s.direction_id,
        st.stop_id,
        st.stop_sequence,
        s.trip_id,
        {{ gtfs_scheduled_ts('s.service_date', 'st.departure_seconds') }} as scheduled_ts
    from {{ ref('int_scheduled_trips') }} s
    join {{ ref('stg_gtfs__stop_times') }} st
        on st.feed_version = s.feed_version and st.trip_id = s.trip_id
    where st.is_timepoint
),

pairs as (
    select
        *,
        lag(trip_id) over w as prev_trip_id,
        lag(stop_sequence) over w as prev_stop_sequence,
        lag(scheduled_ts) over w as prev_scheduled_ts
    from scheduled
    window w as (
        partition by service_date, route_id, direction_id, stop_id
        order by scheduled_ts, trip_id
    )
),

actual as (
    select
        service_date,
        trip_id_scheduled as trip_id,
        trip_stop_sequence as stop_sequence,
        min(actual_ts) as actual_ts
    from {{ ref('timepoint_events') }}
    where measured_event = 'departure' and {{ metrics_filter() }}
    group by service_date, trip_id_scheduled, trip_stop_sequence
),

measured as (
    select
        p.service_date,
        p.route_id,
        p.direction_id,
        p.stop_id,
        p.trip_id,
        p.prev_trip_id,
        p.scheduled_ts,
        hour(p.scheduled_ts) as scheduled_hour,
        epoch(p.scheduled_ts) - epoch(p.prev_scheduled_ts) as scheduled_headway_s,
        epoch(a.actual_ts) - epoch(pa.actual_ts) as actual_headway_s
    from pairs p
    join actual a
        on a.service_date = p.service_date and a.trip_id = p.trip_id
        and a.stop_sequence = p.stop_sequence
    join actual pa
        on pa.service_date = p.service_date and pa.trip_id = p.prev_trip_id
        and pa.stop_sequence = p.prev_stop_sequence
    where p.prev_trip_id is not null
      and p.scheduled_ts > p.prev_scheduled_ts  -- two trips scheduled at the same minute are not a headway
)

select
    *,
    round(actual_headway_s / scheduled_headway_s, 3) as headway_ratio,
    actual_headway_s < {{ var('bunching_threshold_s') }} as is_bunched,
    cast(ceil(scheduled_headway_s * (1 + {{ var('headway_allowance_pct') }} / 100.0) / 60) * 60 as integer)
        as headway_limit_s,
    actual_headway_s <= ceil(scheduled_headway_s * (1 + {{ var('headway_allowance_pct') }} / 100.0) / 60) * 60
        as is_headway_on_time,
    scheduled_headway_s <= {{ var('frequent_headway_max_s') }} as is_frequent
from measured
