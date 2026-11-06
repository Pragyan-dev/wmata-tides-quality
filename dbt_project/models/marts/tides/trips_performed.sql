-- TIDES trips_performed: one row per trip a vehicle was seen operating.
-- trip_id_performed = <GTFS trip_id>-<vehicle_id>, so a trip that changes buses
-- midway becomes two performed trips, which is what happened on the street.

with performed as (
    select
        service_date,
        trip_id,
        vehicle_id,
        arg_max(route_id, event_epoch) as rt_route_id,
        arg_max(trip_schedule_relationship, event_epoch) as vp_schedule_relationship
    from {{ ref('stg_rt__vehicle_positions') }}
    where trip_id is not null
    group by service_date, trip_id, vehicle_id
),

static_trips as (
    select v.service_date, t.*
    from {{ ref('int_service_date_feed_versions') }} v
    join {{ ref('stg_gtfs__trips') }} t using (feed_version)
),

schedule_ends as (
    select
        feed_version,
        trip_id,
        arg_min(stop_id, stop_sequence) as first_stop_id,
        arg_max(stop_id, stop_sequence) as last_stop_id,
        min(departure_seconds) as start_seconds,
        max(arrival_seconds) as end_seconds
    from {{ ref('stg_gtfs__stop_times') }}
    group by feed_version, trip_id
),

actual_ends as (
    select
        service_date,
        trip_id,
        vehicle_id,
        max(actual_departure_ts) filter (where is_first_stop) as actual_start_ts,
        max(actual_arrival_ts) filter (where is_last_stop) as actual_end_ts
    from {{ ref('int_stop_visits_inferred') }}
    group by service_date, trip_id, vehicle_id
),

trip_update_status as (
    select service_date, trip_id, arg_max(trip_schedule_relationship, last_seen_at) as tu_relationship
    from {{ ref('stg_rt__trip_updates') }}
    group by service_date, trip_id
)

select
    p.service_date,
    p.trip_id || '-' || p.vehicle_id as trip_id_performed,
    p.vehicle_id,
    p.trip_id as trip_id_scheduled,
    coalesce(t.route_id, p.rt_route_id) as route_id,
    'Bus' as route_type,
    'Bus' as ntd_mode,
    t.shape_id,
    t.direction_id,
    t.block_id,
    s.first_stop_id as trip_start_stop_id,
    s.last_stop_id as trip_end_stop_id,
    {{ gtfs_scheduled_ts('p.service_date', 's.start_seconds') }} as schedule_trip_start,
    {{ gtfs_scheduled_ts('p.service_date', 's.end_seconds') }} as schedule_trip_end,
    a.actual_start_ts as actual_trip_start,
    a.actual_end_ts as actual_trip_end,
    'In service' as trip_type,
    case coalesce(tu.tu_relationship, p.vp_schedule_relationship)
        when 'SCHEDULED' then 'Scheduled'
        when 'ADDED' then 'Added'
        when 'UNSCHEDULED' then 'Unscheduled'
        when 'CANCELED' then 'Canceled'
        when 'DUPLICATED' then 'Duplicated'
    end as schedule_relationship,
    t.trip_id is not null as is_in_static_gtfs
from performed p
left join static_trips t on t.service_date = p.service_date and t.trip_id = p.trip_id
left join schedule_ends s on s.feed_version = t.feed_version and s.trip_id = p.trip_id
left join actual_ends a
    on a.service_date = p.service_date and a.trip_id = p.trip_id and a.vehicle_id = p.vehicle_id
left join trip_update_status tu on tu.service_date = p.service_date and tu.trip_id = p.trip_id
