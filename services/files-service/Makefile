# files-service: service logic with tests, no server yet (docs/architecture/service-map.md). Part of the root uv
# workspace; storage backends come from packages/ops_storage.
SERVICE_NAME := files-service
SERVICE_STATUS := service logic with tests, no server yet
OWN_VERBS := install test lint typecheck verify clean

##@ Library

install: ## uv sync for the workspace
	uv sync --frozen

lint: ## ruff
	uv run ruff format --check src tests
	uv run ruff check src tests

typecheck: ## pyright
	uv run pyright src tests

test: ## pytest (optional container tests skip without Docker)
	uv run pytest -q -rs

verify: lint typecheck test ## lint, typecheck and test

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

include ../../make/service-stub.mk
