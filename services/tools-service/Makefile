# Tools service: the tool gateway and the tool-module registry on :8720 (ISOLATED=1: :9720), deciding with OPA on :8181.
# PostgreSQL and OPA come from the shared compose stack. Its tables have their own migration chain
# (alembic_version_tools). Registry tests live in tests/; the gateway's still live in ../agents-service/tests/gateway
# while ops_tools reads the agents catalogue (docs/architecture/service-map.md).
STACK_SVC := tools
include ../../make/service-common.mk
.PHONY: install run test test-gateway lint typecheck verify migrate clean openapi openapi-check

PY_DIRS := src tests migrations scripts

##@ Tools service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve in the foreground on :8720 (ISOLATED=1: :9720)
	uv run python -m ops_tools

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: ## Registry and API tests on the test database (starts compose)
	$(MAKE) -C ../agents-service db-up
	$(TEST_DB) uv run pytest

test-gateway: ## Gateway tests, still in agents-service/tests/gateway, which agents-service verify also runs
	$(MAKE) -C ../agents-service db-up
	cd ../agents-service && $(TEST_DB) uv run pytest tests/gateway

verify: lint typecheck test openapi-check ## lint, typecheck, test and the OpenAPI gate

openapi-check: ## openapi.json matches the app, every route named, tagged and typed (or on the shrinking allowlist)
	uv run python scripts/check_openapi.py

openapi: ## Regenerate openapi.json after a route change
	uv run python scripts/check_openapi.py --write

migrate: ## Apply this service's own migrations (version table alembic_version_tools)
	uv run alembic upgrade head

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache
