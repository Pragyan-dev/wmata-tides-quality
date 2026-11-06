-- TIDES stop_visits: one row per scheduled stop of every performed trip that has
-- pings on its shape. Times come from int_stop_visits_inferred.
-- schedule_relationship:
--   'Scheduled'  an arrival or departure time was inferred
--   'Skipped'    no time inferred, and TripUpdates marked the stop SKIPPED
--   'Missing'    no time inferred for any other reason (see interpolation fields)

with visits as (
    select * from {{ ref('int_stop_visits_inferred') }}
),

skipped as (
    select service_date, trip_id, stop_sequence, ever_skipped
    from {{ ref('stg_rt__trip_updates') }}
)

select
    v.service_date,
    v.trip_id || '-' || v.vehicle_id as trip_id_performed,
    v.stop_sequence as trip_stop_sequence,
    v.stop_sequence as scheduled_stop_sequence,
    v.vehicle_id,
    -- Dwell only where both times exist. At the first stop the bus may sit on layover
    -- before the trip, and at the last stop after it, so neither gets a dwell.
    case
        when not v.is_first_stop and not v.is_last_stop
            then cast(round(epoch(v.actual_departure_ts) - epoch(v.actual_arrival_ts)) as integer)
    end as dwell,
    v.stop_id,
    v.is_timepoint as timepoint,
    v.scheduled_arrival_ts as schedule_arrival_time,
    v.scheduled_departure_ts as schedule_departure_time,
    case when not v.is_first_stop then v.actual_arrival_ts end as actual_arrival_time,
    case when not v.is_last_stop then v.actual_departure_ts end as actual_departure_time,
    case
        when (not v.is_first_stop and v.actual_arrival_ts is not null)
          or (not v.is_last_stop and v.actual_departure_ts is not null) then 'Scheduled'
        when coalesce(s.ever_skipped, false) then 'Skipped'
        else 'Missing'
    end as schedule_relationship,
    -- Extra columns for quality checks and metrics. Export drops them from the TIDES files.
    v.is_first_stop,
    v.is_last_stop,
    v.is_out_of_order,
    v.interpolation_gap_s,
    v.arrival_method,
    v.departure_method,
    v.no_visit_reason
from visits v
left join skipped s using (service_date, trip_id, stop_sequence)
