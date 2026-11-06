-- TIDES vehicle_locations: one row per distinct vehicle ping.
-- Field names and allowed values follow spec/tides-v1.0/vehicle_locations.schema.json.
-- Fields the public feed cannot supply (device_id, gps_quality, odometer, deviations)
-- are added as empty columns at export time.

select
    location_ping_id,
    service_date,
    event_ts as event_timestamp,
    case when trip_id is not null then trip_id || '-' || vehicle_id end as trip_id_performed,
    trip_id as trip_id_scheduled,
    current_stop_sequence as trip_stop_sequence,
    current_stop_sequence as scheduled_stop_sequence,
    vehicle_id,
    stop_id,
    case current_status
        when 'INCOMING_AT' then 'Incoming at'
        when 'STOPPED_AT' then 'Stopped at'
        when 'IN_TRANSIT_TO' then 'In transit to'
    end as current_status,
    latitude,
    longitude,
    bearing as heading,
    speed,
    -- Assumption: a bus reporting a trip_id is in service. The feed has no deadhead flag.
    case when trip_id is not null then 'In service' end as trip_type,
    case trip_schedule_relationship
        when 'SCHEDULED' then 'Scheduled'
        when 'ADDED' then 'Added'
    end as schedule_relationship
from {{ ref('stg_rt__vehicle_positions') }}
