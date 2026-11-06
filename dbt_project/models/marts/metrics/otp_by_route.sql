-- On-time performance by route and direction, at the quality level set by
-- metrics_quality_level (default moderate).

select
    e.service_date,
    e.route_id,
    e.direction_id,
    count(distinct e.trip_id_performed) as trips,
    {{ otp_columns() }}
from {{ ref('timepoint_events') }} e
where {{ metrics_filter() }}
group by e.service_date, e.route_id, e.direction_id
