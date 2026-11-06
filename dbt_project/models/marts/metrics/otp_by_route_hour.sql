-- On-time performance by route and scheduled hour, for a route x hour matrix.

select
    e.service_date,
    e.route_id,
    e.scheduled_hour,
    {{ otp_columns() }}
from {{ ref('timepoint_events') }} e
where {{ metrics_filter() }}
group by e.service_date, e.route_id, e.scheduled_hour
