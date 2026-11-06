select
    {{ feed_version_from_filename() }} as feed_version,
    route_id,
    route_short_name,
    route_long_name,
    cast(route_type as integer) as route_type,
    route_color
from {{ source('gtfs', 'routes') }}
