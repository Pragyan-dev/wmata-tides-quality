-- Scheduled trips that ran entirely inside the collected window but that no vehicle
-- was seen operating. This is an upper bound on missed trips: a trip can also be
-- unobserved because its bus sent no trip_id, or sent a wrong one.

with collected as (
    select min(fetched_at) as window_start, max(fetched_at) as window_end
    from {{ ref('stg_collector__fetches') }}
    where feed = 'vehicle_positions' and http_status = 200
),

scheduled as (
    select
        s.service_date,
        s.trip_id,
        s.route_id,
        s.direction_id,
        {{ gtfs_scheduled_ts('s.service_date', 'min(st.departure_seconds)') }} as scheduled_start,
        {{ gtfs_scheduled_ts('s.service_date', 'max(st.arrival_seconds)') }} as scheduled_end
    from {{ ref('int_scheduled_trips') }} s
    join {{ ref('stg_gtfs__stop_times') }} st
        on st.feed_version = s.feed_version and st.trip_id = s.trip_id
    group by s.service_date, s.trip_id, s.route_id, s.direction_id
),

feed_gaps as (
    select fetched_at - to_seconds(seconds_since_prev_fetch) as gap_start, fetched_at as gap_end
    from {{ ref('dq_feed_checks') }}
    where feed = 'vehicle_positions' and missed_polls > 0
),

observed as (
    select distinct service_date, trip_id_scheduled as trip_id from {{ ref('trips_performed') }}
)

select
    s.*,
    o.trip_id is not null as was_observed,
    exists (
        select 1 from feed_gaps g where g.gap_start < s.scheduled_end and g.gap_end > s.scheduled_start
    ) as overlaps_feed_gap
from scheduled s
cross join collected c
left join observed o using (service_date, trip_id)
where s.scheduled_start >= c.window_start and s.scheduled_end <= c.window_end
