# platform-service: the identity issuer on :8710, with API-key introspection on :8711 bound to localhost
# (ISOLATED=1: :9710, :9711). Tenants, teams, members, sessions, API keys and audit; the only service that mints
# tokens (docs/services/platform-service/overview.md). Its tables have their own migration chain
# (alembic_version_platform).
STACK_SVC := platform
include ../../make/service-common.mk
.PHONY: install run test lint typecheck verify migrate clean openapi-check

PY_DIRS := src tests migrations scripts

##@ Platform service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve in the foreground on :8710 and :8711; in dev it seeds team_ops and signs with the dev key
	uv run python -m ops_platform

migrate: ## Apply this service's own migrations (version table alembic_version_platform)
	uv run alembic upgrade head

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: ## pytest on the test database (make db-up)
	$(TEST_DB) uv run pytest

openapi-check: ## openapi.json matches the apps and every operation is typed
	uv run python scripts/check_openapi.py

verify: lint typecheck test openapi-check ## lint, typecheck, test and the OpenAPI gate

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

