-- Trip updates reduced to one row per trip and stop: the last thing the feed said.
-- Raw trip updates repeat every 30 seconds (about 21,000 rows per fetch), so this
-- keeps the model small. Used for skipped stops and trip schedule_relationship.

with source as (
    select * from {{ source('rt', 'trip_updates') }}
    where trip_id is not null
      {{ collection_window('fetch_ts_utc') }}
)

select
    trip_id,
    strptime(start_date, '%Y%m%d')::date as service_date,
    stop_sequence,
    max(route_id) as route_id,
    -- Latest report wins. Ties within one fetch break by value so runs are repeatable.
    arg_max(vehicle_id, (fetch_ts_utc, vehicle_id)) as vehicle_id,
    arg_max(trip_schedule_relationship, (fetch_ts_utc, trip_schedule_relationship))
        as trip_schedule_relationship,
    arg_max(stu_schedule_relationship, (fetch_ts_utc, stu_schedule_relationship))
        as last_stop_schedule_relationship,
    bool_or(stu_schedule_relationship = 'SKIPPED') as ever_skipped,
    to_timestamp(arg_max(arrival_time, (fetch_ts_utc, arrival_time))) as last_predicted_arrival,
    count(*) as n_updates,
    to_timestamp(min(fetch_ts_utc)) as first_seen_at,
    to_timestamp(max(fetch_ts_utc)) as last_seen_at
from source
group by trip_id, start_date, stop_sequence
