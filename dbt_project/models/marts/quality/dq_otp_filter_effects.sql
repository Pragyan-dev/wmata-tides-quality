-- One quality filter at a time: OTP of the timepoint events that pass that single
-- filter, compared with no filter. Shows which data problem moves OTP the most.

with events as (
    select
        *,
        {{ is_on_time('deviation_s', 'is_last_timepoint') }} as on_time
    from {{ ref('timepoint_events') }}
    where actual_ts is not null
),

filters as (
    select 'none' as filter_name, true as keep, * from events
    union all select 'gap <= {{ var("moderate_max_gap_s") }} s',
        interpolation_gap_s <= {{ var('moderate_max_gap_s') }}, * from events
    union all select 'gap <= {{ var("strict_max_gap_s") }} s',
        interpolation_gap_s <= {{ var('strict_max_gap_s') }}, * from events
    union all select 'off-route <= {{ var("strict_max_off_route_pct") }}%',
        pct_off_route <= {{ var('strict_max_off_route_pct') }}, * from events
    union all select 'enough pings', not too_few_pings, * from events
    union all select 'time from shape method', time_method = 'shape', * from events
    union all select 'no impossible-speed ping', n_impossible_speed = 0, * from events
    union all select 'no stale ping', n_stale = 0, * from events
    union all select 'no coverage gap', not has_coverage_gap, * from events
    union all select 'no missed polls', not overlaps_feed_gap, * from events
    union all select 'trip inside window', not cut_by_window, * from events
    union all select 'all timepoints inferred', is_complete, * from events
),

summary as (
    select
        filter_name,
        count(*) filter (where keep) as timepoint_events,
        round(100.0 * avg(on_time::int) filter (where keep), 2) as otp_pct
    from filters
    group by filter_name
)

select
    s.filter_name,
    s.timepoint_events,
    round(100.0 * s.timepoint_events / n.timepoint_events, 1) as pct_of_events_kept,
    s.otp_pct,
    round(s.otp_pct - n.otp_pct, 2) as otp_change_pp
from summary s
cross join (select * from summary where filter_name = 'none') n
order by abs(s.otp_pct - n.otp_pct) desc
