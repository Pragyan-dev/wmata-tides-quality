-- On-time performance by scheduled hour (local time), systemwide.

select
    e.service_date,
    e.scheduled_hour,
    count(distinct e.route_id) as routes,
    {{ otp_columns() }}
from {{ ref('timepoint_events') }} e
where {{ metrics_filter() }}
group by e.service_date, e.scheduled_hour
