# ---- build stage: install dependencies and dbt packages ----
FROM python:3.14-slim AS build

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml README.md ./
COPY revintel/ revintel/
RUN python -m venv /venv && /venv/bin/pip install ".[snowflake,azure]"

COPY dbt/ dbt/
RUN /venv/bin/dbt deps --project-dir dbt --profiles-dir dbt

# ---- runtime stage: slim image, non-root user ----
FROM python:3.14-slim

RUN useradd --create-home --uid 10001 revintel
WORKDIR /app
COPY --from=build /venv /venv
COPY --from=build --chown=revintel /app/dbt dbt/
COPY --chown=revintel sql/ sql/
RUN chown revintel /app

# REVINTEL_HOME points the installed package at /app for dbt/, sql/, data/ and output/
ENV PATH="/venv/bin:$PATH" PYTHONUNBUFFERED=1 LOG_FORMAT=json \
    REVINTEL_HOME=/app REVINTEL_DUCKDB_PATH=/app/output/revintel.duckdb
USER revintel

ENTRYPOINT ["revintel"]
CMD ["run", "--target", "local", "--generate"]
