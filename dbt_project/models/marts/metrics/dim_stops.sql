-- Stop attributes from the most recent static GTFS version.

with latest as (
    select feed_version from {{ ref('stg_gtfs__feed_versions') }}
    order by collection_date desc limit 1
),

timepoint_stops as (
    select distinct stop_id
    from {{ ref('stg_gtfs__stop_times') }}
    where is_timepoint and feed_version = (select feed_version from latest)
)

select
    s.stop_id,
    s.stop_code,
    s.stop_name,
    s.stop_lat,
    s.stop_lon,
    s.stop_id in (select stop_id from timepoint_stops) as is_timepoint
from {{ ref('stg_gtfs__stops') }} s
where s.feed_version = (select feed_version from latest)
