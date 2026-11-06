-- Every trip the static GTFS schedules on each service date: service_ids active from
-- calendar.txt (weekday and date range), plus calendar_dates additions (exception 1),
-- minus calendar_dates removals (exception 2).

with dates as (
    select service_date, feed_version from {{ ref('int_service_date_feed_versions') }}
),

from_calendar as (
    select d.service_date, c.feed_version, c.service_id
    from dates d
    join {{ ref('stg_gtfs__calendar') }} c
        on c.feed_version = d.feed_version
        and d.service_date between c.start_date and c.end_date
    where case dayofweek(d.service_date)
            when 0 then c.sunday when 1 then c.monday when 2 then c.tuesday
            when 3 then c.wednesday when 4 then c.thursday when 5 then c.friday
            when 6 then c.saturday
          end
),

exceptions as (
    select d.service_date, cd.feed_version, cd.service_id, cd.exception_type
    from dates d
    join {{ ref('stg_gtfs__calendar_dates') }} cd
        on cd.feed_version = d.feed_version and cd.service_date = d.service_date
),

active as (
    (
        select service_date, feed_version, service_id from from_calendar
        union
        select service_date, feed_version, service_id from exceptions where exception_type = 1
    )
    except
    select service_date, feed_version, service_id from exceptions where exception_type = 2
)

select a.service_date, t.feed_version, t.trip_id, t.route_id, t.direction_id, t.service_id
from active a
join {{ ref('stg_gtfs__trips') }} t using (feed_version, service_id)
