-- Known answers for the GTFS time macros. Returns a row for every case that is wrong.
-- GTFS times count from "noon minus 12 hours" local time on the service date, which is
-- midnight on normal days and 1 hour off on DST change days.

with cases as (
    select '25:10:00' as gtfs_time, date '2026-11-06' as service_date,
           timestamptz '2026-11-07 01:10:00-05:00' as expected
    union all
    select '9:59:59', date '2026-11-06', timestamptz '2026-11-06 09:59:59-05:00'
    union all
    -- Fall back (2026-11-01): noon EST minus 12 h is 01:00 EDT, so 08:00:00 is 08:00 EST.
    select '08:00:00', date '2026-11-01', timestamptz '2026-11-01 08:00:00-05:00'
    union all
    -- Spring forward (2026-03-08): noon EDT minus 12 h is 23:00 EST the day before,
    -- so 08:00:00 is 08:00 EDT.
    select '08:00:00', date '2026-03-08', timestamptz '2026-03-08 08:00:00-04:00'
)

select *, {{ gtfs_scheduled_ts('service_date', gtfs_time_to_seconds('gtfs_time')) }} as got
from cases
where {{ gtfs_scheduled_ts('service_date', gtfs_time_to_seconds('gtfs_time')) }} <> expected
