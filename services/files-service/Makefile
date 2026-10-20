# files-service: file bytes for every service on :8750 (docs/services/files-service/overview.md): uploads with a proxy
# route for the local backend, sniffing, sha256 dedupe, downloads, legal holds and the scan hook. Its tables have their
# own migration chain (alembic_version_files); storage backends come from packages/ops_storage.
SERVICE_NAME := files-service
SERVICE_STATUS := first slice: hosted upload, complete, download, delete, legal hold on the local backend
STACK_SVC := files

PY_DIRS := src tests migrations scripts

##@ Files service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve on :8750
	uv run python -m ops_files

migrate: ## Apply this service's own migrations (version table alembic_version_files)
	uv run alembic upgrade head

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: ## pytest on the test database (make db-up); LocalStack and Azurite tests skip without those containers
	$(TEST_DB) uv run pytest -rfs

verify: lint typecheck test openapi-check ## lint, typecheck, test and the OpenAPI gate

openapi-check: ## openapi.json matches the app, every route named, tagged and typed (or on the shrinking allowlist)
	uv run python scripts/check_openapi.py

openapi: ## Regenerate openapi.json after a route change
	uv run python scripts/check_openapi.py --write

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

include ../../make/service-common.mk
