{# Filter raw feed rows to the optional collection window set by the
   collected_after / collected_before vars. #}
{% macro collection_window(fetch_col) -%}
    {%- if var('collected_after') %} and {{ fetch_col }} >= epoch(timestamptz '{{ var("collected_after") }}'){% endif -%}
    {%- if var('collected_before') %} and {{ fetch_col }} < epoch(timestamptz '{{ var("collected_before") }}'){% endif -%}
{%- endmacro %}
