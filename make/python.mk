# The uv workspace: packages/ plus the services.
.PHONY: python-install python-verify sbom test test-impacted agent-guard

##@ Python

# Every check runs even after one fails, and the run fails at the end listing each failed check: a check that
# stopped the run hid every red after it, and the rule-5 failure reached HEAD behind a lint error that way.
# VERIFY_FAILED is one temporary file per make run, made on first use, so builders verifying at once never share it.
VERIFY_FAILED = $(eval VERIFY_FAILED := $(shell mktemp -t ops-verify.XXXXXX))$(VERIFY_FAILED)
KEEP = $(ROOT)/scripts/keep_going.sh $(VERIFY_FAILED)

python-install: ## uv sync for packages/ and services/; from UV_DEFAULT_INDEX instead when it is set (behind a mirror)
ifdef UV_DEFAULT_INDEX
	bash $(ROOT)/scripts/install_via_mirror.sh
else
	uv sync --frozen
endif

# Tests never run on the stack's database: each make run makes its own throwaway one (OPS_TEST_DATABASE_URL, make/env.mk)
# on the stack's PostgreSQL, so no second stack is needed beside `make up`.
test: db-up ## Tests on a throwaway database: PKG=packages/<x>|services/<x> runs that member's (T= some files); no PKG runs what changed since origin/main
ifdef PKG
	@[ -d "$(PKG)" ] || { echo "make test: no folder $(PKG)"; exit 2; }
ifneq ($(wildcard $(PKG)/Makefile),)
	@$(MAKE) -s -C "$(PKG)" test $(if $(T),T="$(T)")
else
	@$(TEST_DB) uv run --directory "$(PKG)" pytest -q $(or $(T),tests)
endif
else
	@scripts/verify-changed.sh "$$(git merge-base origin/main HEAD)"
endif

# What a builder runs while working: only the tests the change can affect, with the pick and the reason printed.
# PLAN=1 prints the pick and stops. CI and nightly keep the whole suites (`make verify`).
test-impacted: ## Run only the tests a change since BASE (default origin/main) can affect; PLAN=1 prints the pick only
	@uv run python scripts/impacted_tests.py --base "$(or $(BASE),origin/main)" $(if $(PLAN),--list)

# Registered like git-rules.py: one PreToolUse hook on Bash in the checkout's own Claude Code project settings (not tracked).
agent-guard: ## Check the agent wait guard and print the hook entry that registers it
	@python3 scripts/agent-guard.py --self-test
	@echo 'register: {"matcher":"Bash","hooks":[{"type":"command","command":"python3 \"$$CLAUDE_PROJECT_DIR\"/scripts/agent-guard.py"}]} under hooks.PreToolUse'

python-verify: ## Lint and type-check packages, then verify each service with model keys unset
	@rm -f $(VERIFY_FAILED)
	$(KEEP) uv run ruff format --check packages
	$(KEEP) uv run ruff check packages
	@# Database code only in store packages, and the layers' import directions (.importlinter). Seconds.
	$(KEEP) uv run lint-imports --no-logo
	@mkdir -p $(VERIFY_LOGS)
	@# The suites side by side; each writes its own log, printed below in a fixed order once all have ended.
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

# The suites share nothing but the machine, so they run side by side: one after another they used one of 14
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
	@$(call pool_job,$@,set -e; for p in ops_ingest ops_policy ops_identity ops_access ops_email ops_signin ops_service_kit; do (cd packages/$$p && uv run pytest); done; cd packages/ops_store && uv run pytest tests/test_schema_version.py)
pool-deploy:
	@$(call pool_job,$@,uv run pytest deploy/database/tests && uv run pytest -q deploy/k8s/tests)

sbom: ## Regenerate docs/architecture/dependencies.md from uv.lock (run after any lock change)
	uv run python scripts/sbom.py
