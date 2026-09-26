{# Round and cast a monetary expression to a fixed-precision decimal. #}
{% macro money(expression) -%}
    cast(round({{ expression }}, 2) as decimal(18, 2))
{%- endmacro %}
