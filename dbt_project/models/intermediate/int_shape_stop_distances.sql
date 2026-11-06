-- Distance along the shape of every stop on every shape, found by projecting the
-- stop onto the nearest shape segment.
-- A shape that loops can pass near the same stop twice. If the nearest point puts a
-- stop before the stop that comes earlier in the sequence, it is flagged
-- is_out_of_order and stop_visits does not infer a time for it.

with shape_stops as (
    select distinct t.feed_version, t.shape_id, st.stop_sequence, st.stop_id
    from {{ ref('stg_gtfs__stop_times') }} st
    join {{ ref('stg_gtfs__trips') }} t using (feed_version, trip_id)
    where t.feed_version in (select feed_version from {{ ref('int_service_date_feed_versions') }})
),

located as (
    select
        ss.*,
        {{ to_x_m('s.stop_lon') }} as px,
        {{ to_y_m('s.stop_lat') }} as py
    from shape_stops ss
    join {{ ref('stg_gtfs__stops') }} s using (feed_version, stop_id)
),

candidates as (
    select l.*, seg.segment_seq, seg.x1, seg.y1, seg.x2, seg.y2, seg.seg_len_m, seg.seg_start_m
    from located l
    cross join {{ neighbor_offsets() }} o
    join {{ ref('int_shape_segments') }} seg
        on seg.feed_version = l.feed_version
        and seg.shape_id = l.shape_id
        and seg.cell_x = {{ grid_cell('l.px') }} + o.dx
        and seg.cell_y = {{ grid_cell('l.py') }} + o.dy
),

projected as (
    select *, {{ segment_fraction('px', 'py') }} as f
    from candidates
),

nearest as (
    select
        feed_version,
        shape_id,
        stop_sequence,
        stop_id,
        seg_start_m + f * seg_len_m as stop_dist_m,
        sqrt(pow(px - (x1 + f * (x2 - x1)), 2) + pow(py - (y1 + f * (y2 - y1)), 2))
            as stop_snap_distance_m
    from projected
    qualify row_number() over (
        partition by feed_version, shape_id, stop_sequence
        order by sqrt(pow(px - (x1 + f * (x2 - x1)), 2) + pow(py - (y1 + f * (y2 - y1)), 2))
    ) = 1
)

select
    *,
    coalesce(stop_dist_m < max(stop_dist_m) over (
        partition by feed_version, shape_id order by stop_sequence
        rows between unbounded preceding and 1 preceding
    ), false) as is_out_of_order
from nearest
