# runner-service: code tools' Python functions on WASM (CPython 3.12 for WASI under wasmtime), no network, no secrets,
# on :8770 (docs/services/runner-service/overview.md). No database.
SERVICE_NAME := runner-service
SERVICE_STATUS := first slice: Python on WASM, ops.call back through tools-service, memory, time and call limits
OWN_VERBS := install run test lint typecheck verify wasm clean

PY_DIRS := src tests

##@ Runner service

install: wasm ## uv sync for the workspace, and the pinned Python build
	uv sync --frozen

wasm: ## Fetch the pinned CPython WASI build into OPS_RUNNER_CACHE_DIR (.data/runner) and check its SHA-256
	uv run python -m ops_runner.fetch

run: wasm ## Serve on :8770
	uv run python -m ops_runner

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(PY_DIRS)

test: wasm ## pytest; runs real guests on the pinned build
	uv run pytest

verify: lint typecheck test ## lint, typecheck and test

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

include ../../make/service-stub.mk
