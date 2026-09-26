.PHONY: install lint test test-fast run dbt-docs docker clean

install:  ## install package with dev tooling and git hooks
	pip install -e ".[dev,snowflake,azure]"
	pre-commit install

lint:
	ruff check .
	ruff format --check .
	mypy

test:  ## unit + end-to-end (runs dbt)
	pytest --cov

test-fast:  ## unit tests only
	pytest -m "not slow"

run:  ## full local pipeline on DuckDB
	revintel run --target local --generate

dbt-docs:  ## browse lineage and model docs at http://localhost:8080
	dbt docs generate --project-dir dbt --profiles-dir dbt --target local
	dbt docs serve --project-dir dbt --profiles-dir dbt --port 8080

docker:
	docker build -t revintel:local .
	docker run --rm revintel:local

clean:
	rm -rf data output dbt/target dbt/logs .pytest_cache .mypy_cache .ruff_cache
