{# True when a timepoint event is on time under the configured window.
   Default (WMATA): 2 minutes early to 7 minutes late; at the last timepoint only
   lateness counts. #}
{% macro is_on_time(deviation_s, is_last_timepoint) -%}
    (case
        when {{ is_last_timepoint }} then {{ deviation_s }} <= {{ var('otp_late_s') }}
        else {{ deviation_s }} between -{{ var('otp_early_s') }} and {{ var('otp_late_s') }}
    end)
{%- endmacro %}

{% macro is_early(deviation_s, is_last_timepoint) -%}
    (not {{ is_last_timepoint }} and {{ deviation_s }} < -{{ var('otp_early_s') }})
{%- endmacro %}

{% macro is_late(deviation_s) -%}
    ({{ deviation_s }} > {{ var('otp_late_s') }})
{%- endmacro %}

{# Timepoint events kept at each quality filter level. #}
{% macro passes_filter(level) -%}
    {%- if level == 'loose' -%}
    true
    {%- elif level == 'moderate' -%}
    (interpolation_gap_s <= {{ var('moderate_max_gap_s') }}
     and pct_off_route <= {{ var('moderate_max_off_route_pct') }}
     and not too_few_pings)
    {%- elif level == 'strict' -%}
    (interpolation_gap_s <= {{ var('strict_max_gap_s') }}
     and pct_off_route <= {{ var('strict_max_off_route_pct') }}
     and not too_few_pings
     and time_method = 'shape'
     and n_impossible_speed = 0
     and n_stale = 0
     and not has_coverage_gap
     and not overlaps_feed_gap
     and not cut_by_window
     and is_complete)
    {%- endif -%}
{%- endmacro %}

{# The quality filter the metrics marts use (var metrics_quality_level). #}
{% macro metrics_filter() -%}
    (actual_ts is not null and {{ passes_filter(var('metrics_quality_level')) }})
{%- endmacro %}

{# Standard OTP columns for a group of timepoint events. #}
{% macro otp_columns() -%}
    count(*) as timepoint_events,
    count(*) filter (where is_on_time) as on_time_events,
    count(*) filter (where is_early) as early_events,
    count(*) filter (where is_late) as late_events,
    round(100.0 * avg(is_on_time::int), 2) as otp_pct,
    round(100.0 * avg(is_early::int), 2) as early_pct,
    round(100.0 * avg(is_late::int), 2) as late_pct,
    round(median(deviation_s) / 60.0, 2) as median_deviation_min,
    round(quantile_cont(deviation_s, 0.9) / 60.0, 2) as p90_deviation_min
{%- endmacro %}
