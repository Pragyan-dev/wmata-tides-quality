-- Every ping on a trip, snapped to its trip's shape.
--
-- Pass 1: snap to the nearest segment within max_snap_distance_m.
-- Pass 2: where a shape passes the same place more than once (loops, out-and-back
--   sections), several segments can be about equally close. Among segments within
--   30 m of the best one, pick the one whose distance along the shape agrees with
--   the median of the neighboring pings' pass 1 results.
-- Progress: the running maximum of distance along the shape, so GPS jitter
--   backward does not make the bus appear to reverse.
--
-- Pings farther than max_snap_distance_m from the shape keep along_m = null
-- (off route: detour, deadhead, or bad GPS).

with pings as (
    select
        p.location_ping_id,
        p.service_date,
        p.trip_id,
        p.vehicle_id,
        p.event_ts,
        p.event_epoch,
        p.latitude,
        p.longitude,
        v.feed_version,
        t.shape_id,
        {{ to_x_m('p.longitude') }} as px,
        {{ to_y_m('p.latitude') }} as py
    from {{ ref('stg_rt__vehicle_positions') }} p
    join {{ ref('int_service_date_feed_versions') }} v using (service_date)
    join {{ ref('stg_gtfs__trips') }} t
        on t.feed_version = v.feed_version and t.trip_id = p.trip_id
    where p.trip_id is not null
      and p.latitude is not null
      and p.longitude is not null
),

candidates as (
    select
        p.location_ping_id,
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
    select *, min(snap_m) over (partition by location_ping_id) as best_snap_m
    from candidates
    where snap_m <= {{ var('max_snap_distance_m') }}
),

pass1 as (
    select location_ping_id, along_m as along_pass1_m, snap_m as snap_pass1_m
    from close_candidates
    qualify row_number() over (partition by location_ping_id order by snap_m) = 1
),

with_neighbors as (
    select
        p.*,
        p1.along_pass1_m,
        median(p1.along_pass1_m) over (
            partition by p.service_date, p.trip_id, p.vehicle_id
            order by p.event_epoch
            rows between {{ var('smoothing_window_pings') }} preceding
                 and {{ var('smoothing_window_pings') }} following
        ) as neighbor_median_m
    from pings p
    left join pass1 p1 using (location_ping_id)
),

pass2 as (
    select c.location_ping_id, c.along_m, c.snap_m
    from close_candidates c
    join with_neighbors n using (location_ping_id)
    where c.snap_m <= c.best_snap_m + 30
    qualify row_number() over (
        partition by c.location_ping_id
        order by abs(c.along_m - n.neighbor_median_m), c.snap_m
    ) = 1
)

select
    n.location_ping_id,
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
left join pass2 p2 using (location_ping_id)
