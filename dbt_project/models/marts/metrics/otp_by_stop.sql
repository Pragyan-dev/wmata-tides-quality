-- On-time performance by timepoint stop, across all routes that serve it.

select
    e.service_date,
    e.stop_id,
    s.stop_name,
    s.stop_lat,
    s.stop_lon,
    count(distinct e.route_id) as routes,
    {{ otp_columns() }}
from {{ ref('timepoint_events') }} e
left join {{ ref('dim_stops') }} s using (stop_id)
where {{ metrics_filter() }}
group by e.service_date, e.stop_id, s.stop_name, s.stop_lat, s.stop_lon
