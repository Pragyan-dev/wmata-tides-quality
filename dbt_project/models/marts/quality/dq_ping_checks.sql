-- One row per distinct ping with a true/false flag for each ping-level check.
--   outside_service_area  position outside the bounding box of all stops plus a buffer
--   impossible_speed      implied speed from the vehicle's previous ping is faster than
--                         dq_max_speed_mps over a jump of at least dq_min_jump_m
--   stale_ping            the ping was already dq_stale_ping_age_s old when first fetched,
--                         or the feed kept repeating it for at least that long
--   off_route             on a trip, but more than max_snap_distance_m from the trip's shape
--   trip_not_in_static    the feed's trip_id is not in the static GTFS for that date
--   stop_not_in_static    the feed's stop_id is not in the static GTFS for that date

with pings as (
    select
        p.*,
        v.feed_version,
        lag(p.latitude) over w as prev_lat,
        lag(p.longitude) over w as prev_lon,
        lag(p.event_epoch) over w as prev_epoch
    from {{ ref('stg_rt__vehicle_positions') }} p
    join {{ ref('int_service_date_feed_versions') }} v using (service_date)
    window w as (partition by p.vehicle_id order by p.event_epoch)
),

service_area as (
    select
        min(stop_lat) - {{ var('dq_service_area_buffer_m') }} / {{ var('meters_per_deg_lat') }} as min_lat,
        max(stop_lat) + {{ var('dq_service_area_buffer_m') }} / {{ var('meters_per_deg_lat') }} as max_lat,
        min(stop_lon) - {{ var('dq_service_area_buffer_m') }} / {{ var('meters_per_deg_lon') }} as min_lon,
        max(stop_lon) + {{ var('dq_service_area_buffer_m') }} / {{ var('meters_per_deg_lon') }} as max_lon
    from {{ ref('stg_gtfs__stops') }}
),

static_trips as (
    select feed_version, trip_id, route_id from {{ ref('stg_gtfs__trips') }}
),

static_stops as (
    select feed_version, stop_id from {{ ref('stg_gtfs__stops') }}
),

measured as (
    select
        p.*,
        {{ haversine_m('p.prev_lat', 'p.prev_lon', 'p.latitude', 'p.longitude') }} as jump_m,
        p.event_epoch - p.prev_epoch as jump_s
    from pings p
)

select
    m.location_ping_id,
    m.service_date,
    m.vehicle_id,
    m.trip_id,
    coalesce(t.route_id, m.route_id) as route_id,
    m.event_ts,
    hour(m.event_ts) as event_hour,
    m.jump_m,
    m.jump_s,
    case when m.jump_s > 0 then m.jump_m / m.jump_s end as implied_speed_mps,
    m.latitude is null or m.longitude is null as missing_position,
    coalesce(
        m.latitude not between a.min_lat and a.max_lat
        or m.longitude not between a.min_lon and a.max_lon,
        false
    ) as outside_service_area,
    coalesce(
        m.jump_m >= {{ var('dq_min_jump_m') }}
        and m.jump_m / greatest(m.jump_s, 1) > {{ var('dq_max_speed_mps') }},
        false
    ) as impossible_speed,
    m.ping_age_s >= {{ var('dq_stale_ping_age_s') }}
        or (m.times_seen - 1) * 30 >= {{ var('dq_stale_ping_age_s') }} as stale_ping,
    coalesce(m.trip_id is not null and not s.is_on_route, false) as off_route,
    m.trip_id is not null and t.trip_id is null as trip_not_in_static,
    m.stop_id is not null and st.stop_id is null as stop_not_in_static
from measured m
cross join service_area a
left join static_trips t on t.feed_version = m.feed_version and t.trip_id = m.trip_id
left join static_stops st on st.feed_version = m.feed_version and st.stop_id = m.stop_id
left join {{ ref('int_pings_snapped') }} s
    on s.location_ping_id = m.location_ping_id and s.ping_source = 'own_trip'
