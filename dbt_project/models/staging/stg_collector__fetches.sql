-- One row per fetch attempt from data/logs/fetches.csv, typed.
-- Unlike the Parquet files, this includes failed and empty fetches.

select
    cast(fetch_ts_utc as bigint) as fetch_epoch,
    to_timestamp(cast(fetch_ts_utc as bigint)) as fetched_at,
    feed,
    cast(nullif(http_status, '') as integer) as http_status,
    cast(nullif(bytes, '') as bigint) as bytes,
    cast(nullif(entity_count, '') as integer) as entity_count,
    cast(nullif(header_ts, '') as bigint) as header_epoch,
    cast(nullif(header_age_s, '') as integer) as header_age_s,
    cast(nullif(duration_ms, '') as integer) as duration_ms,
    cast(nullif(attempts, '') as integer) as attempts,
    nullif(error, '') as error
from {{ source('collector', 'fetches') }}
where feed in ('vehicle_positions', 'trip_updates')
    {{ collection_window('cast(fetch_ts_utc as bigint)') }}
