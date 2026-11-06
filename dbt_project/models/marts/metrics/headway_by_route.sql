-- Headway adherence and bunching by route and direction.

select
    service_date,
    route_id,
    direction_id,
    count(*) as headway_pairs,
    count(*) filter (where is_frequent) as frequent_pairs,
    round(median(scheduled_headway_s) / 60.0, 1) as median_scheduled_headway_min,
    round(median(actual_headway_s) / 60.0, 1) as median_actual_headway_min,
    round(median(headway_ratio), 2) as median_headway_ratio,
    count(*) filter (where is_bunched) as bunched_pairs,
    round(100.0 * avg(is_bunched::int), 2) as bunched_pct,
    round(100.0 * avg(is_headway_on_time::int) filter (where is_frequent), 2)
        as frequent_headway_on_time_pct
from {{ ref('headways') }}
group by service_date, route_id, direction_id
