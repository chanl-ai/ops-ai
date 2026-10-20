# kb-service: department knowledge bases, their file sources, and passages with page and section, on :8740
# (docs/services/kb-service/overview.md). Its tables have their own migration chain (alembic_version_kb).
SERVICE_NAME := kb-service
SERVICE_STATUS := first slice: knowledge bases, file sources, Postgres full-text retrieval
OWN_VERBS := install run test lint typecheck verify migrate clean openapi openapi-check

PY_DIRS := src tests migrations scripts

##@ Knowledge service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve on :8740
	uv run python -m ops_kb

migrate: ## Apply this service's own migrations (version table alembic_version_kb)
	uv run alembic upgrade head

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: ## pytest on the test database (make db-up)
	$(TEST_DB) uv run pytest

verify: lint typecheck test openapi-check ## lint, typecheck, test and the OpenAPI gate

openapi-check: ## openapi.json matches the app, every route named, tagged and typed (or on the shrinking allowlist)
	uv run python scripts/check_openapi.py

openapi: ## Regenerate openapi.json after a route change
	uv run python scripts/check_openapi.py --write

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

include ../../make/service-stub.mk
