-- The static GTFS version to use for each service date: the most recent version
-- downloaded on or before that date. Schedules change, so a ping must be compared
-- to the schedule that was in effect that day.
-- A service date earlier than the first download falls back to the first version
-- and is flagged.

with dates as (
    select distinct service_date from {{ ref('stg_rt__vehicle_positions') }}
),

versions as (
    select * from {{ ref('stg_gtfs__feed_versions') }}
),

matched as (
    select d.service_date, v.feed_version, v.collection_date
    from dates d
    asof left join versions v on d.service_date >= v.collection_date
)

select
    service_date,
    coalesce(feed_version, (select feed_version from versions order by collection_date limit 1))
        as feed_version,
    feed_version is null as used_fallback_version
from matched
