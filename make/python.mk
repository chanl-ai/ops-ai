# The uv workspace: packages/ plus the services.
.PHONY: python-install python-verify sbom

##@ Python

# Every check runs even after one fails, and the run fails at the end listing each failed check (c-367): a check that
# stopped the run hid every red after it, and c-222's rule-5 failure reached HEAD behind a lint error that way.
# VERIFY_FAILED is one temporary file per make run, made on first use, so builders verifying at once never share it.
VERIFY_FAILED = $(eval VERIFY_FAILED := $(shell mktemp -t ops-verify.XXXXXX))$(VERIFY_FAILED)
KEEP = $(ROOT)/scripts/keep_going.sh $(VERIFY_FAILED)

python-install: ## uv sync for packages/ and services/
	uv sync --frozen

python-verify: ## Lint and type-check packages, then verify each service with model keys unset
	@rm -f $(VERIFY_FAILED)
	$(KEEP) uv run ruff format --check packages
	$(KEEP) uv run ruff check packages
	$(KEEP) uv run pyright packages
	@# Database code only in store packages, and the layers' import directions (.importlinter, c-346). Seconds.
	$(KEEP) uv run lint-imports --no-logo
	cd packages/ops_ingest && $(KEEP) uv run pytest
	cd packages/ops_policy && $(KEEP) uv run pytest
	cd packages/ops_identity && $(KEEP) uv run pytest
	cd packages/ops_access && $(KEEP) uv run pytest
	cd packages/ops_email && $(KEEP) uv run pytest
	cd packages/ops_signin && $(KEEP) uv run pytest
	cd packages/ops_store && $(KEEP) uv run pytest tests/test_schema_version.py
	$(KEEP) uv run pytest deploy/database/tests
	$(KEEP) uv run pytest -q deploy/k8s/tests
	$(KEEP) $(MAKE) -k -C services/files-service verify
	$(KEEP) $(MAKE) -k -C services/documents-service verify
	$(KEEP) $(MAKE) -k -C services/runner-service verify
	$(KEEP) $(MAKE) -k -C services/models-service verify
	$(KEEP) $(MAKE) -k -C $(SVC_DIR_kb) verify
	$(KEEP) $(MAKE) -k -C services/platform-service verify
	$(KEEP) $(MAKE) -k -C $(SVC_DIR_tools) verify
	$(KEEP) env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY $(MAKE) -k -C $(SVC_DIR_agents) verify
	cd packages/ops_store && $(KEEP) env OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL) uv run pytest
	cd packages/ops_engine && $(KEEP) env OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL) uv run pytest
	$(KEEP) uv run python scripts/store_inventory.py --check
	$(KEEP) uv run python scripts/roles_matrix.py --check
	$(KEEP) uv run python scripts/check_access_exceptions.py
	$(KEEP) uv run python scripts/check_access_exceptions.py --commits
	$(KEEP) uv run python scripts/sbom.py --check
	$(KEEP) uv run python deploy/k8s/generate.py --check
	$(KEEP) uv run pytest -q scripts/tests
	@# Database-specific code outside ops_store, unbounded key columns, long names; a raised baseline row needs a trailer.
	$(KEEP) uv run python scripts/check_portable_store.py --strict
	$(KEEP) uv run python scripts/check_portable_store.py --commits
	@$(ROOT)/scripts/keep_going.sh --report $(VERIFY_FAILED)

sbom: ## Regenerate docs/architecture/dependencies.md from uv.lock (run after any lock change)
	uv run python scripts/sbom.py
