# Agents service on :8700 (ISOLATED=1: :9700). Model keys come from the environment (OPENAI_API_KEY, or
# ANTHROPIC_API_KEY for a claude-* alias); never commit a .env, run under your secrets manager. Run from this folder or
# with `make -C services/agents-service <target>`; the root `make up` runs it in the background.
STACK_SVC := agents
include ../../make/service-common.mk
.PHONY: install run test lint typecheck verify migrate clean db-up db-down standards sbom openapi openapi-check

export PYDANTIC_AI_NO_BANNER := 1

PY_DIRS := src tests scripts migrations experiments
# Migrations are linted but not type-checked, as before the move.
TYPED_DIRS := src tests scripts experiments

##@ Agents service

install: ## uv sync for the workspace
	uv sync --frozen

run: ## Serve in the foreground on :8700 (ISOLATED=1: :9700)
	uv run python -m ops_agents.api

lint: ## ruff format check and lint
	uv run ruff format --check $(PY_DIRS)
	uv run ruff check $(PY_DIRS)

typecheck: ## Strict pyright
	uv run pyright $(TYPED_DIRS)

test: ## pytest on the test database (needs db-up)
	$(TEST_DB) uv run pytest tests

verify: lint typecheck db-up test standards openapi-check ## lint, typecheck, test and standards; the root runs it with model keys unset

migrate: ## Alembic upgrade head
	uv run alembic upgrade head

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

db-up: ## PostgreSQL and OPA in compose (same as the root db-up)
	$(COMPOSE) up -d --wait --no-recreate postgres opa  # never recreate the shared containers (make/db.mk)

db-down: ## Stop compose
	$(COMPOSE) down

standards: ## Service standards check
	uv run python scripts/check_standards.py

openapi-check: ## openapi.json matches the app, every route named, tagged and typed (or on the shrinking allowlist)
	uv run python scripts/check_openapi.py

openapi: ## Regenerate openapi.json after a route change
	uv run python scripts/check_openapi.py --write

sbom: ## Regenerate docs/architecture/dependencies.md
	uv run python scripts/sbom.py
