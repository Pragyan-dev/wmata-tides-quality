-- Inferred arrival and departure time at every scheduled stop of every observed trip.
--
-- A stop sits at stop_dist_m along the shape. The bus "arrives" when its progress
-- reaches stop_dist_m - stop_zone_m and "departs" when it reaches
-- stop_dist_m + stop_zone_m. For each of those two points, find the last ping before
-- and the first ping after, then interpolate the time linearly by distance.
--
-- Stops get no time when: the stop could not be placed on the shape in order
-- (is_out_of_order), the bus has no ping before or after the point (trip observed
-- only in part), or the stop is past the farthest point the bus reached.
-- interpolation_gap_s records how far apart the bracketing pings were, so quality
-- filters can drop visits based on long gaps.

with observed_trips as (
    select
        service_date, trip_id, vehicle_id, feed_version, shape_id,
        min(progress_m) as first_progress_m,
        max(progress_m) as last_progress_m
    from {{ ref('int_pings_snapped') }}
    where is_on_route
    group by service_date, trip_id, vehicle_id, feed_version, shape_id
),

scheduled as (
    select
        o.service_date,
        o.trip_id,
        o.vehicle_id,
        o.feed_version,
        o.shape_id,
        st.stop_sequence,
        st.stop_id,
        st.arrival_seconds,
        st.departure_seconds,
        st.is_timepoint,
        st.stop_sequence = min(st.stop_sequence) over trip as is_first_stop,
        st.stop_sequence = max(st.stop_sequence) over trip as is_last_stop,
        d.stop_dist_m,
        coalesce(d.is_out_of_order, true) as is_out_of_order,
        o.first_progress_m,
        o.last_progress_m
    from observed_trips o
    join {{ ref('stg_gtfs__stop_times') }} st
        on st.feed_version = o.feed_version and st.trip_id = o.trip_id
    left join {{ ref('int_shape_stop_distances') }} d
        on d.feed_version = o.feed_version
        and d.shape_id = o.shape_id
        and d.stop_sequence = st.stop_sequence
    window trip as (partition by o.service_date, o.trip_id, o.vehicle_id)
),

-- Progress never decreases. Adding ping_seq * 1 micrometer makes it strictly
-- increasing, so "last ping at or before a point" is always the latest such ping.
pings as (
    select
        service_date, trip_id, vehicle_id, event_epoch,
        progress_m + ping_seq * 1e-6 as progress_key
    from {{ ref('int_pings_snapped') }}
    where is_on_route
),

edges as (
    select
        *,
        stop_dist_m - {{ var('stop_zone_m') }} as arrive_at_m,
        stop_dist_m + {{ var('stop_zone_m') }} as depart_at_m
    from scheduled
    where not is_out_of_order
),

arrive_before as (
    select e.*, p.event_epoch as ab_t, p.progress_key as ab_d
    from edges e
    asof left join pings p
        on e.service_date = p.service_date and e.trip_id = p.trip_id
        and e.vehicle_id = p.vehicle_id and e.arrive_at_m >= p.progress_key
),

arrive_after as (
    select e.*, p.event_epoch as aa_t, p.progress_key as aa_d
    from arrive_before e
    asof left join pings p
        on e.service_date = p.service_date and e.trip_id = p.trip_id
        and e.vehicle_id = p.vehicle_id and e.arrive_at_m < p.progress_key
),

depart_before as (
    select e.*, p.event_epoch as db_t, p.progress_key as db_d
    from arrive_after e
    asof left join pings p
        on e.service_date = p.service_date and e.trip_id = p.trip_id
        and e.vehicle_id = p.vehicle_id and e.depart_at_m >= p.progress_key
),

depart_after as (
    select e.*, p.event_epoch as da_t, p.progress_key as da_d
    from depart_before e
    asof left join pings p
        on e.service_date = p.service_date and e.trip_id = p.trip_id
        and e.vehicle_id = p.vehicle_id and e.depart_at_m < p.progress_key
),

interpolated as (
    select
        service_date, trip_id, vehicle_id, stop_sequence,
        ab_t + (arrive_at_m - ab_d) / (aa_d - ab_d) * (aa_t - ab_t) as arrival_epoch,
        db_t + (depart_at_m - db_d) / (da_d - db_d) * (da_t - db_t) as departure_epoch,
        aa_t - ab_t as arrival_gap_s,
        da_t - db_t as departure_gap_s
    from depart_after
)

select
    s.service_date,
    s.trip_id,
    s.vehicle_id,
    s.feed_version,
    s.shape_id,
    s.stop_sequence,
    s.stop_id,
    s.is_timepoint,
    s.is_first_stop,
    s.is_last_stop,
    s.stop_dist_m,
    s.is_out_of_order,
    {{ gtfs_scheduled_ts('s.service_date', 's.arrival_seconds') }} as scheduled_arrival_ts,
    {{ gtfs_scheduled_ts('s.service_date', 's.departure_seconds') }} as scheduled_departure_ts,
    to_timestamp(i.arrival_epoch) as actual_arrival_ts,
    to_timestamp(i.departure_epoch) as actual_departure_ts,
    i.arrival_gap_s,
    i.departure_gap_s,
    greatest(i.arrival_gap_s, i.departure_gap_s) as interpolation_gap_s,
    case
        when i.arrival_epoch is not null or i.departure_epoch is not null then null
        when s.is_out_of_order then 'stop_not_placed_on_shape'
        when s.stop_dist_m + {{ var('stop_zone_m') }} <= s.first_progress_m then 'bus_first_seen_past_stop'
        when s.stop_dist_m - {{ var('stop_zone_m') }} >= s.last_progress_m then 'bus_never_reached_stop'
        else 'other'
    end as no_visit_reason
from scheduled s
left join interpolated i using (service_date, trip_id, vehicle_id, stop_sequence)
