{# Flat x/y in meters from the region origin. Simple and accurate enough for
   distances of a few hundred meters (see docs/METHODOLOGY.md). #}
{% macro to_x_m(lon) -%}
    (({{ lon }} - {{ var('origin_lon') }}) * {{ var('meters_per_deg_lon') }})
{%- endmacro %}

{% macro to_y_m(lat) -%}
    (({{ lat }} - {{ var('origin_lat') }}) * {{ var('meters_per_deg_lat') }})
{%- endmacro %}

{% macro grid_cell(meters) -%}
    cast(floor({{ meters }} / {{ var('grid_cell_m') }}) as integer)
{%- endmacro %}

{# Haversine distance in meters, for speed checks between pings. #}
{% macro haversine_m(lat1, lon1, lat2, lon2) -%}
    (2 * 6371000 * asin(sqrt(
        pow(sin(radians({{ lat2 }} - {{ lat1 }}) / 2), 2)
        + cos(radians({{ lat1 }})) * cos(radians({{ lat2 }}))
        * pow(sin(radians({{ lon2 }} - {{ lon1 }}) / 2), 2)
    )))
{%- endmacro %}

{# Position along a segment, from 0 (start) to 1 (end), of the closest point to (px, py).
   Expects columns x1, y1, x2, y2, seg_len_m from int_shape_segments. #}
{% macro segment_fraction(px, py) -%}
    greatest(0.0, least(1.0,
        (({{ px }} - x1) * (x2 - x1) + ({{ py }} - y1) * (y2 - y1)) / (seg_len_m * seg_len_m)
    ))
{%- endmacro %}

{# The 9 grid cells around a point: its own cell and the 8 neighbors. #}
{% macro neighbor_offsets() -%}
    (select dx, dy from range(-1, 2) t1(dx), range(-1, 2) t2(dy))
{%- endmacro %}
