select
    cast(collection_date as date) as collection_date,
    feed_version
from {{ source('gtfs', 'feed_versions') }}
