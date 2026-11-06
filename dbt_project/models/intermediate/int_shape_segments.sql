-- Each route shape as a chain of straight segments in flat x/y meters, with the
-- distance along the shape where each segment starts. WMATA's GTFS has no
-- shape_dist_traveled, so this computes it.

with points as (
    select
        feed_version,
        shape_id,
        shape_pt_sequence,
        {{ to_x_m('shape_pt_lon') }} as x,
        {{ to_y_m('shape_pt_lat') }} as y
    from {{ ref('stg_gtfs__shapes') }}
    where feed_version in (select feed_version from {{ ref('int_service_date_feed_versions') }})
),

segments as (
    select
        feed_version,
        shape_id,
        shape_pt_sequence as segment_seq,
        x as x1,
        y as y1,
        lead(x) over w as x2,
        lead(y) over w as y2
    from points
    window w as (partition by feed_version, shape_id order by shape_pt_sequence)
),

measured as (
    select *, sqrt(pow(x2 - x1, 2) + pow(y2 - y1, 2)) as seg_len_m
    from segments
    where x2 is not null
)

select
    feed_version,
    shape_id,
    segment_seq,
    x1, y1, x2, y2,
    seg_len_m,
    coalesce(sum(seg_len_m) over (
        partition by feed_version, shape_id order by segment_seq
        rows between unbounded preceding and 1 preceding
    ), 0) as seg_start_m,
    -- Grid cell of the segment midpoint. Lookups search the 3 x 3 cells around a
    -- point, which reaches at least one full cell (250 m) in every direction.
    {{ grid_cell('(x1 + x2) / 2') }} as cell_x,
    {{ grid_cell('(y1 + y2) / 2') }} as cell_y
from measured
where seg_len_m > 0  -- repeated shape points add nothing
