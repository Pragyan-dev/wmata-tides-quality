-- One row per distinct vehicle ping.
-- WMATA repeats a ping in consecutive fetches until the bus reports again, so the
-- same (vehicle_id, vehicle_ts) can appear in several fetches. Keep the first fetch
-- and record how many times it was seen (used by the stale-ping quality check).

with source as (
    select * from {{ source('rt', 'vehicle_positions') }}
    where vehicle_id is not null
      and vehicle_ts is not null
      {{ collection_window('fetch_ts_utc') }}
),

ranked as (
    select
        *,
        row_number() over (partition by vehicle_id, vehicle_ts order by fetch_ts_utc) as fetch_rank,
        count(*) over (partition by vehicle_id, vehicle_ts) as times_seen
    from source
)

select
    vehicle_id || '-' || cast(vehicle_ts as varchar) as location_ping_id,
    vehicle_id,
    trip_id,
    route_id,
    direction_id,
    -- Service date: the trip's start_date when the bus is on a trip, else the local
    -- calendar date of the ping. The session time zone is America/New_York.
    coalesce(
        strptime(start_date, '%Y%m%d')::date,
        cast(to_timestamp(vehicle_ts) as date)
    ) as service_date,
    to_timestamp(vehicle_ts) as event_ts,
    to_timestamp(fetch_ts_utc) as first_fetched_at,
    vehicle_ts as event_epoch,
    fetch_ts_utc - vehicle_ts as ping_age_s,
    latitude,
    longitude,
    bearing,
    speed,
    current_stop_sequence,
    stop_id,
    current_status,
    trip_schedule_relationship,
    occupancy_status,
    times_seen,
    cast(date as date) as collection_date
from ranked
where fetch_rank = 1
