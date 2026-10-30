# The uv workspace: packages/ plus the services.
.PHONY: python-install python-verify sbom

##@ Python

# Every check runs even after one fails, and the run fails at the end listing each failed check (c-367): a check that
# stopped the run hid every red after it, and c-222's rule-5 failure reached HEAD behind a lint error that way.
# VERIFY_FAILED is one temporary file per make run, made on first use, so builders verifying at once never share it.
VERIFY_FAILED = $(eval VERIFY_FAILED := $(shell mktemp -t ops-verify.XXXXXX))$(VERIFY_FAILED)
KEEP = $(ROOT)/scripts/keep_going.sh $(VERIFY_FAILED)

python-install: ## uv sync for packages/ and services/; from UV_DEFAULT_INDEX instead when it is set (behind a mirror)
ifdef UV_DEFAULT_INDEX
	bash $(ROOT)/scripts/install_via_mirror.sh
else
	uv sync --frozen
endif

python-verify: ## Lint and type-check packages, then verify each service with model keys unset
	@rm -f $(VERIFY_FAILED)
	$(KEEP) uv run ruff format --check packages
	$(KEEP) uv run ruff check packages
	@# Database code only in store packages, and the layers' import directions (.importlinter, c-346). Seconds.
	$(KEEP) uv run lint-imports --no-logo
	@mkdir -p $(VERIFY_LOGS)
	@# The suites side by side (c-566); each writes its own log, printed below in a fixed order once all have ended.
	-@$(MAKE) -s -k -j$(VERIFY_JOBS) $(VERIFY_POOL) VERIFY_FAILED=$(VERIFY_FAILED) VERIFY_LOGS=$(VERIFY_LOGS)
	@for job in $(VERIFY_POOL); do echo "== $$job"; cat $(VERIFY_LOGS)/$$job.log 2>/dev/null; done; rm -rf $(VERIFY_LOGS)
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

# The suites share nothing but the machine, so they run side by side (c-566): one after another they used one of 14
# cores and a full run took about 21 minutes. Each service verify and each database-backed package suite gets its own
# test database, <db>_<name>, so none waits on another's locks or reads its rows. agents-service, the longest suite,
# starts first so the run does not end waiting on it alone. VERIFY_JOBS sets the width: the Mac is shared by builders.
VERIFY_JOBS ?= 4
VERIFY_LOGS = $(eval VERIFY_LOGS := $(shell mktemp -d -t ops-verify-logs.XXXXXX))$(VERIFY_LOGS)
VERIFY_POOL := pool-agents pool-tools pool-platform pool-pyright pool-kb pool-models pool-files pool-documents \
  pool-runner pool-store pool-engine pool-packages pool-deploy
.PHONY: $(VERIFY_POOL)
# One pool job: `$(call pool_job,<name>,<command>)` runs the command through keep_going into <name>.log.
pool_job = $(KEEP) bash -c '$(2)' > $(VERIFY_LOGS)/$(1).log 2>&1
db_for = $(OPS_TEST_DATABASE_URL)_$(1)

pool-agents:
	@$(call pool_job,$@,env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY OPS_TEST_DATABASE_URL=$(call db_for,agents) $(MAKE) -k -C $(SVC_DIR_agents) verify)
pool-tools:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,tools) $(MAKE) -k -C $(SVC_DIR_tools) verify)
pool-platform:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,platform) $(MAKE) -k -C services/platform-service verify)
pool-kb:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,kb) $(MAKE) -k -C $(SVC_DIR_kb) verify)
pool-models:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,models) $(MAKE) -k -C services/models-service verify)
pool-files:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,files) $(MAKE) -k -C services/files-service verify)
pool-documents:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,documents) $(MAKE) -k -C services/documents-service verify)
pool-runner:
	@$(call pool_job,$@,OPS_TEST_DATABASE_URL=$(call db_for,runner) $(MAKE) -k -C services/runner-service verify)
pool-pyright:
	@$(call pool_job,$@,uv run pyright packages)
pool-store:
	@$(call pool_job,$@,uv run python scripts/test_db.py $(call db_for,store) && cd packages/ops_store && OPS_DATABASE_URL=$(call db_for,store) uv run pytest)
pool-engine:
	@$(call pool_job,$@,uv run python scripts/test_db.py $(call db_for,engine) && cd packages/ops_engine && OPS_DATABASE_URL=$(call db_for,engine) uv run pytest)
pool-packages:
	@$(call pool_job,$@,set -e; for p in ops_ingest ops_policy ops_identity ops_access ops_email ops_signin; do (cd packages/$$p && uv run pytest); done; cd packages/ops_store && uv run pytest tests/test_schema_version.py)
pool-deploy:
	@$(call pool_job,$@,uv run pytest deploy/database/tests && uv run pytest -q deploy/k8s/tests)

sbom: ## Regenerate docs/architecture/dependencies.md from uv.lock (run after any lock change)
	uv run python scripts/sbom.py
