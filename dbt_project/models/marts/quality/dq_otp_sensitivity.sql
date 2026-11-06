-- On-time performance under three quality filter levels, to show how much data
-- quality moves the headline number.
--   loose     every timepoint event with an inferred time
--   moderate  interpolation gap <= 120 s, trip off-route share <= 20%, enough pings
--   strict    gap <= 60 s, off-route <= 5%, enough pings, no impossible-speed or stale
--             pings, no coverage gap, no missed polls, trip fully inside the collected
--             window, and every timepoint on the trip inferred
-- Thresholds are dbt vars (dbt_project.yml).

with events as (
    select * from {{ ref('timepoint_events') }}
    where actual_ts is not null
),

levels as (
    {% for level in ['loose', 'moderate', 'strict'] %}
    select '{{ level }}' as filter_level, {{ loop.index }} as level_order, *
    from events
    where {{ passes_filter(level) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

scored as (
    select
        *,
        {{ is_on_time('deviation_s', 'is_last_timepoint') }} as on_time,
        {{ is_early('deviation_s', 'is_last_timepoint') }} as early,
        {{ is_late('deviation_s') }} as late
    from levels
),

summary as (
    select
        filter_level,
        level_order,
        count(*) as timepoint_events,
        count(distinct trip_id_performed) as trips,
        count(distinct route_id) as routes,
        count(*) filter (where on_time) as on_time_events,
        round(100.0 * avg(on_time::int), 2) as otp_pct,
        round(100.0 * avg(early::int), 2) as early_pct,
        round(100.0 * avg(late::int), 2) as late_pct,
        round(median(deviation_s) / 60.0, 2) as median_deviation_min
    from scored
    group by filter_level, level_order
)

select
    s.*,
    round(100.0 * s.timepoint_events / l.timepoint_events, 1) as pct_of_loose_events,
    round(s.otp_pct - l.otp_pct, 2) as otp_change_vs_loose_pp
from summary s
cross join (select * from summary where filter_level = 'loose') l
order by s.level_order
