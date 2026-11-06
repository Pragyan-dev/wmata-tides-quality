{# Seconds after midnight from a GTFS time like "25:10:00". GTFS times can pass 24:00. #}
{% macro gtfs_time_to_seconds(col) -%}
    (
        cast(split_part({{ col }}, ':', 1) as integer) * 3600
        + cast(split_part({{ col }}, ':', 2) as integer) * 60
        + cast(split_part({{ col }}, ':', 3) as integer)
    )
{%- endmacro %}

{# GTFS measures stop times from "noon minus 12 hours" on the service date, in local
   time. This is midnight except on DST change days, when it is 23:00 or 01:00. #}
{% macro gtfs_service_day_start(service_date) -%}
    (timezone('{{ var("agency_timezone") }}', cast({{ service_date }} as timestamp) + interval 12 hour)
     - interval 12 hour)
{%- endmacro %}

{% macro gtfs_scheduled_ts(service_date, seconds) -%}
    ({{ gtfs_service_day_start(service_date) }} + to_seconds({{ seconds }}))
{%- endmacro %}

{# Static GTFS files live in static/<feed_version>/<table>.parquet. #}
{% macro feed_version_from_filename() -%}
    regexp_extract(filename, '/([0-9a-f]{12})/[a-z_]+\.parquet$', 1)
{%- endmacro %}
