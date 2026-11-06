-- The sensitivity analysis per route: OTP at each filter level and how far the
-- strict number is from the loose one.

with events as (
    select * from {{ ref('timepoint_events') }}
    where actual_ts is not null
),

per_level as (
    {% for level in ['loose', 'moderate', 'strict'] %}
    select
        route_id,
        '{{ level }}' as filter_level,
        count(*) as timepoint_events,
        round(100.0 * avg({{ is_on_time('deviation_s', 'is_last_timepoint') }}::int), 2) as otp_pct
    from events
    where {{ passes_filter(level) }}
    group by route_id
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select
    route_id,
    max(timepoint_events) filter (where filter_level = 'loose') as loose_events,
    max(timepoint_events) filter (where filter_level = 'strict') as strict_events,
    max(otp_pct) filter (where filter_level = 'loose') as loose_otp_pct,
    max(otp_pct) filter (where filter_level = 'moderate') as moderate_otp_pct,
    max(otp_pct) filter (where filter_level = 'strict') as strict_otp_pct,
    round(
        max(otp_pct) filter (where filter_level = 'strict')
        - max(otp_pct) filter (where filter_level = 'loose'), 2
    ) as strict_minus_loose_pp
from per_level
group by route_id
