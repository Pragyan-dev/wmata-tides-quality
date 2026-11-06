{# Fails for every combination of `columns` that appears more than once.
   Used for TIDES composite primary keys. #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
