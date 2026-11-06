select
    {{ feed_version_from_filename() }} as feed_version,
    service_id,
    strptime(date, '%Y%m%d')::date as service_date,
    cast(exception_type as integer) as exception_type
from {{ source('gtfs', 'calendar_dates') }}
