select
    {{ feed_version_from_filename() }} as feed_version,
    trip_id,
    stop_id,
    cast(stop_sequence as integer) as stop_sequence,
    {{ gtfs_time_to_seconds('arrival_time') }} as arrival_seconds,
    {{ gtfs_time_to_seconds('departure_time') }} as departure_seconds,
    -- WMATA marks the stops used for on-time performance with timepoint = 1.
    coalesce(timepoint = '1', false) as is_timepoint
from {{ source('gtfs', 'stop_times') }}
