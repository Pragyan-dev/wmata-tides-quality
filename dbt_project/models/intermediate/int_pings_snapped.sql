-- Pings snapped to each trip's shape, one row per (trip, ping).
--
-- Which pings: every ping the feed tags with the trip ("own_trip"), plus the same
-- vehicle's pings from up to terminal_window_s before the trip's first ping
-- ("before_trip") and after its last ping ("after_trip"). WMATA attaches the trip_id
-- only after the bus leaves the first stop and moves to the next trip before the bus
-- reaches the last stop, so without these pings the first departure and the last
-- arrival are rarely observable. Borrowed pings are kept only if they snap within
-- terminal_zone_m of the start (before_trip) or the end (after_trip) of the shape.
--
-- Pass 1: snap to the nearest segment within max_snap_distance_m.
-- Pass 2: where a shape passes the same place more than once (loops, out-and-back
--   sections), several segments can be about equally close. Among segments within
--   30 m of the best one, pick the one whose distance along the shape agrees with
--   the median of the neighboring pings' pass 1 results.
-- Progress: the running maximum of distance along the shape, so GPS jitter
--   backward does not make the bus appear to reverse.
--
-- Own-trip pings farther than max_snap_distance_m from the shape keep along_m = null
-- (off route: detour, deadhead, or bad GPS).

with all_pings as (
    select
        p.*,
        {{ to_x_m('p.longitude') }} as px,
        {{ to_y_m('p.latitude') }} as py
    from {{ ref('stg_rt__vehicle_positions') }} p
    where p.latitude is not null and p.longitude is not null
),

own as (
    select
        p.location_ping_id, p.service_date, p.trip_id, p.vehicle_id,
        p.event_ts, p.event_epoch, p.latitude, p.longitude, p.px, p.py,
        v.feed_version, t.shape_id,
        'own_trip' as ping_source
    from all_pings p
    join {{ ref('int_service_date_feed_versions') }} v using (service_date)
    join {{ ref('stg_gtfs__trips') }} t
        on t.feed_version = v.feed_version and t.trip_id = p.trip_id
    where p.trip_id is not null
),

trip_bounds as (
    select
        service_date, trip_id, vehicle_id, feed_version, shape_id,
        min(event_epoch) as first_epoch,
        max(event_epoch) as last_epoch
    from own
    group by service_date, trip_id, vehicle_id, feed_version, shape_id
),

borrowed as (
    select
        p.location_ping_id, b.service_date, b.trip_id, b.vehicle_id,
        p.event_ts, p.event_epoch, p.latitude, p.longitude, p.px, p.py,
        b.feed_version, b.shape_id,
        case when p.event_epoch < b.first_epoch then 'before_trip' else 'after_trip' end
            as ping_source
    from trip_bounds b
    join all_pings p
        on p.vehicle_id = b.vehicle_id
        and p.trip_id is distinct from b.trip_id
        and (
            p.event_epoch between b.first_epoch - {{ var('terminal_window_s') }} and b.first_epoch - 1
            or p.event_epoch between b.last_epoch + 1 and b.last_epoch + {{ var('terminal_window_s') }}
        )
),

pings as (
    select
        *,
        service_date || '|' || trip_id || '|' || vehicle_id || '|' || location_ping_id
            as trip_ping_key
    from (select * from own union all select * from borrowed)
),

shape_lengths as (
    select feed_version, shape_id, max(seg_start_m + seg_len_m) as shape_length_m
    from {{ ref('int_shape_segments') }}
    group by feed_version, shape_id
),

candidates as (
    select
        p.trip_ping_key,
        seg.seg_start_m + f.f * seg.seg_len_m as along_m,
        sqrt(
            pow(p.px - (seg.x1 + f.f * (seg.x2 - seg.x1)), 2)
            + pow(p.py - (seg.y1 + f.f * (seg.y2 - seg.y1)), 2)
        ) as snap_m
    from pings p
    cross join {{ neighbor_offsets() }} o
    join {{ ref('int_shape_segments') }} seg
        on seg.feed_version = p.feed_version
        and seg.shape_id = p.shape_id
        and seg.cell_x = {{ grid_cell('p.px') }} + o.dx
        and seg.cell_y = {{ grid_cell('p.py') }} + o.dy
    cross join lateral (
        select {{ segment_fraction('p.px', 'p.py') }} as f
    ) f
),

close_candidates as (
    select *, min(snap_m) over (partition by trip_ping_key) as best_snap_m
    from candidates
    where snap_m <= {{ var('max_snap_distance_m') }}
),

pass1 as (
    select trip_ping_key, along_m as along_pass1_m
    from close_candidates
    qualify row_number() over (partition by trip_ping_key order by snap_m) = 1
),

-- Drop borrowed pings that are not near the right end of the shape.
kept as (
    select p.*, p1.along_pass1_m
    from pings p
    left join pass1 p1 using (trip_ping_key)
    join shape_lengths sl using (feed_version, shape_id)
    where p.ping_source = 'own_trip'
       or (p.ping_source = 'before_trip' and p1.along_pass1_m <= {{ var('terminal_zone_m') }})
       or (p.ping_source = 'after_trip'
           and p1.along_pass1_m >= sl.shape_length_m - {{ var('terminal_zone_m') }})
),

with_neighbors as (
    select
        *,
        median(along_pass1_m) over (
            partition by service_date, trip_id, vehicle_id
            order by event_epoch
            rows between {{ var('smoothing_window_pings') }} preceding
                 and {{ var('smoothing_window_pings') }} following
        ) as neighbor_median_m
    from kept
),

pass2 as (
    select c.trip_ping_key, c.along_m, c.snap_m
    from close_candidates c
    join with_neighbors n using (trip_ping_key)
    where c.snap_m <= c.best_snap_m + 30
    qualify row_number() over (
        partition by c.trip_ping_key
        order by abs(c.along_m - n.neighbor_median_m), c.snap_m
    ) = 1
)

select
    n.location_ping_id,
    n.ping_source,
    n.service_date,
    n.trip_id,
    n.vehicle_id,
    n.feed_version,
    n.shape_id,
    n.event_ts,
    n.event_epoch,
    n.latitude,
    n.longitude,
    p2.along_m,
    p2.snap_m as snap_distance_m,
    n.along_pass1_m,
    p2.along_m is not null as is_on_route,
    max(p2.along_m) over (
        partition by n.service_date, n.trip_id, n.vehicle_id
        order by n.event_epoch
        rows between unbounded preceding and current row
    ) as progress_m,
    row_number() over (
        partition by n.service_date, n.trip_id, n.vehicle_id order by n.event_epoch
    ) as ping_seq
from with_neighbors n
left join pass2 p2 using (trip_ping_key)
