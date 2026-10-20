# documents-service on :8760 (docs/services/documents-service/overview.md): extractions, corrections, document
# types, samples and test runs; it reads bytes through files-service and never holds them. Its tables have their
# own migration chain (alembic_version_documents).
SERVICE_NAME := documents-service
SERVICE_STATUS := extraction and document types moved from files-service (c-256)
STACK_SVC := documents

PY_DIRS := src tests migrations scripts

##@ Documents service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve on :8760
	uv run python -m ops_documents

migrate: ## Apply this service's own migrations (version table alembic_version_documents)
	uv run alembic upgrade head

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: ## pytest on the test database (make db-up)
	$(TEST_DB) uv run pytest -rfs

verify: lint typecheck test openapi-check ## lint, typecheck, test and the OpenAPI gate

openapi-check: ## openapi.json matches the app, every route named, tagged and typed (or on the shrinking allowlist)
	uv run python scripts/check_openapi.py

openapi: ## Regenerate openapi.json after a route change
	uv run python scripts/check_openapi.py --write

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

include ../../make/service-common.mk
