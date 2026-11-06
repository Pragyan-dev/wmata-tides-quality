-- Route attributes from the most recent static GTFS version.

with latest as (
    select feed_version from {{ ref('stg_gtfs__feed_versions') }}
    order by collection_date desc limit 1
)

select
    route_id,
    route_short_name,
    route_long_name,
    route_short_name || ' ' || route_long_name as route_label,
    '#' || route_color as route_color_hex
from {{ ref('stg_gtfs__routes') }}
where feed_version = (select feed_version from latest)
