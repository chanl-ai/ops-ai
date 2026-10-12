# The uv workspace: packages/ plus the agents, tools and files services.
.PHONY: python-install python-verify

##@ Python

python-install: ## uv sync for packages/ and services/
	uv sync --frozen

python-verify: ## Lint and type-check packages, then verify each service with model keys unset
	uv run ruff format --check packages
	uv run ruff check packages
	uv run pyright packages
	cd packages/ops_ingest && uv run pytest
	cd packages/ops_policy && uv run pytest
	cd packages/ops_identity && uv run pytest
	$(MAKE) -C services/files-service verify
	$(MAKE) -C services/models-service verify
	$(MAKE) -C services/platform-service verify
	$(MAKE) -C $(SVC_DIR_tools) verify
	env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY $(MAKE) -C $(SVC_DIR_agents) verify
	cd packages/ops_store && OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL) uv run pytest
	uv run python scripts/store_inventory.py --check
