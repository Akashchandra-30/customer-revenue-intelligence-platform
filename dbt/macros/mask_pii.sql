{#
  Post-hook: attach the Snowflake dynamic masking policy (created in sql/00_setup.sql)
  to a PII column. Roles other than REVINTEL_TRANSFORMER see a masked value.
  No-op on DuckDB.
#}
{% macro mask_pii(relation, column) -%}
    {%- if target.type == 'snowflake' -%}
        alter table {{ relation }} modify column {{ column }} set masking policy {{ target.database }}.ops.pii_email_mask
    {%- else -%}
        select 1
    {%- endif -%}
{%- endmacro %}
