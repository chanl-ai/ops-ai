# The one list of checks. `make verify` (through python-verify), the pull-request `checks` job in ci.yml, the push
# check in verify-changed.sh and pre-commit (`make checks STAGED=1`) all run `make checks`, so a check added here runs
# in every one of them and none can run a shorter list. A check is a name in CHECKS, the command that runs it and, for
# pre-commit, the staged paths that can change its result. Each is proven red by its own test or `--self-test`.
.PHONY: checks checks-list checks-history ci-local gha-verify requeue

##@ Checks

# The interpreter and tools each check runs on. verify-staged.sh points them at the checkout's own environment, since a
# `uv run` inside the export of a commit would install every member again.
PY ?= uv run python

# Who judges a baseline rise (scripts/baseline_history.py). Every run except `make checks-history` only defers: it prints
# the rise as not checked and passes, because the review is read from GitHub there. A run that sets the variable itself
# (CI's maintainer-review job) keeps its value. Unset outside make, the history checks fail.
REVIEW_GIVEN := $(OPS_STANDARDS_REVIEW)
export OPS_STANDARDS_REVIEW ?= deferred
PYTEST ?= $(PY) -m pytest -q -p no:cacheprovider
LINT_IMPORTS ?= uv run lint-imports --no-logo
PYRIGHT ?= uv run pyright

CHECKS = \
  access-exceptions access-exceptions-commits access-exceptions-self-test \
  portable-store portable-store-commits \
  config-literals config-literals-commits \
  typed-boundaries typed-boundaries-commits \
  console-baselines console-baselines-commits \
  tests-typecheck-self-test tests-typecheck-commits \
  isolation-markings isolation-sites \
  store-inventory roles-matrix sbom k8s-base \
  ratchet-history lint-imports sdk-drift api-changelog api-changes-gap changelog-entries console-standards \
  downgrades migration-heads token-lifetime cross-service standards service-standards service-standards-self-test list-routes gateway-routes \
  ci-steps ci-steps-self-test ci-local-self-test new-migration-self-test builder-watch-self-test usecase-outputs \
  staging-hold-tests quarantine quarantine-self-test ci-usecases-self-test pr-flow-self-test lane-self-test

# Access decided outside can(), the exceptions each lane may still hold, and the trailer a new line needs.
CHECK_ACCESS_PATHS = ^(services|packages)/[^/]+/src/.*\.py$$|^apps/(console|embed)/src/|^access-exceptions-allowlist\.txt$$|^docs/architecture/roles-and-permissions\.md$$|^scripts/(check_access_exceptions\.py|access-baselines/)
check-run.access-exceptions = $(PY) scripts/check_access_exceptions.py
check-paths.access-exceptions = $(CHECK_ACCESS_PATHS)
check-run.access-exceptions-commits = $(PY) scripts/check_access_exceptions.py --commits
check-paths.access-exceptions-commits = $(CHECK_ACCESS_PATHS)
check-run.access-exceptions-self-test = $(PY) scripts/check_access_exceptions.py --self-test
check-paths.access-exceptions-self-test = ^scripts/check_access_exceptions\.py$$

# Storage code that runs on PostgreSQL and not on SQL Server, beyond the member's portable-baseline.txt.
CHECK_PORTABLE_PATHS = ^(services|packages)/[^/]+/(src|migrations)/.*\.py$$|portable-baseline\.txt$$|^scripts/check_portable_store\.py$$
check-run.portable-store = $(PY) scripts/check_portable_store.py --strict
check-paths.portable-store = $(CHECK_PORTABLE_PATHS)
# The history checks read commits already made, so a staged commit can only change them by touching a baseline file.
check-run.portable-store-commits = $(PY) scripts/check_portable_store.py --commits
check-paths.portable-store-commits = (^|/)(portable|list-slice)-baseline\.txt$$

# A loopback fallback anywhere; a literal timeout or HTTP client beyond the member's config-literals-baseline.txt.
CHECK_CONFIG_PATHS = ^(services|packages)/[^/]+/(src/.*\.py|config-literals-baseline\.txt)$$|^scripts/check_config_literals\.py$$
check-run.config-literals = $(PY) scripts/check_config_literals.py --strict
check-paths.config-literals = $(CHECK_CONFIG_PATHS)
check-run.config-literals-commits = $(PY) scripts/check_config_literals.py --commits
check-paths.config-literals-commits = (^|/)config-literals-baseline\.txt$$

# A dict, gather, bare task, loose body or untyped reply beyond the member's typed-boundaries-baseline.txt; any print.
check-run.typed-boundaries = $(PY) scripts/check_typed_boundaries.py --strict
check-paths.typed-boundaries = ^(services|packages)/[^/]+/(src/.*\.py|typed-boundaries-baseline\.txt)$$|^scripts/check_typed_boundaries\.py$$
# The console's JSON baselines (data, palette, reuse): the history check the .txt ones have, and a self-test that plants a rise.
check-run.console-baselines = $(PY) scripts/check_console_baselines.py --self-test
check-paths.console-baselines = ^scripts/(check_console_baselines|baseline_history)\.py$$
check-run.console-baselines-commits = $(PY) scripts/check_console_baselines.py --commits
check-paths.console-baselines-commits = ^apps/console/scripts/[\w-]*baseline[\w-]*\.json$$
check-run.typed-boundaries-commits = $(PY) scripts/check_typed_boundaries.py --commits
check-paths.typed-boundaries-commits = (^|/)typed-boundaries-baseline\.txt$$
# Type errors in test files beyond the member's tests-typecheck-baseline.txt (the typecheck targets below run it).
check-run.tests-typecheck-self-test = $(PY) scripts/check_tests_typecheck.py --self-test
check-paths.tests-typecheck-self-test = ^scripts/(check_tests_typecheck|baseline_history)\.py$$
check-run.tests-typecheck-commits = $(PY) scripts/check_tests_typecheck.py --commits
check-paths.tests-typecheck-commits = (^|/)tests-typecheck-baseline\.txt$$

# Every table marked and indexed; the raw transaction, savepoint, relay and loop-health sites each service still holds.
check-run.isolation-markings = $(PYTEST) deploy/database/tests/test_isolation_markings.py deploy/database/tests/test_indexes.py
check-paths.isolation-markings = ^deploy/database/|^(services|packages)/[^/]+/(src|migrations)/
check-run.isolation-sites = $(PYTEST) packages/ops_store/tests/test_isolation_sites.py packages/ops_store/tests/test_relay_sites.py packages/ops_store/tests/test_loop_health.py
check-paths.isolation-sites = ^packages/ops_store/|^(services|packages)/[^/]+/(src|tests)/.*\.py$$

# The waiting lists of the pytest ratchets only fall, by their history (scripts/baseline_history.py).
check-run.ratchet-history = $(PYTEST) packages/ops_store/tests deploy/database/tests -k falls_in_the_history
check-paths.ratchet-history = ^packages/ops_store/tests/(isolation_sites|relay_sites|loop_health)/|^deploy/database/tests/test_indexes\.py$$

# Files written from code match it.
check-run.store-inventory = $(PY) scripts/store_inventory.py --check
check-paths.store-inventory = ^(services|packages)/[^/]+/(src|migrations)/|^docs/architecture/data\.md$$|^scripts/store_inventory\.py$$
check-run.roles-matrix = $(PY) scripts/roles_matrix.py --check
check-paths.roles-matrix = ^(services|packages)/[^/]+/(src|seed)/|^docs/architecture/roles-and-permissions\.md$$|^scripts/roles_matrix\.py$$
check-run.sbom = $(PY) scripts/sbom.py --check
check-paths.sbom = (^|/)pyproject\.toml$$|^uv\.lock$$|^docs/architecture/dependencies\.md$$
check-run.k8s-base = $(PY) deploy/k8s/generate.py --check
check-paths.k8s-base = ^deploy/compose/app\.yaml$$|^deploy/k8s/|^(services|packages)/[^/]+/src/[^/]+/settings\.py$$
check-run.sdk-drift = $(PY) sdk/generate.py --check
check-paths.sdk-drift = ^sdk/|^services/[^/]+/openapi\.json$$
# The SDK's next-major changelog lists every breaking row of the API changes page, and the page names every changed route.
check-run.api-changelog = $(PY) sdk/changelog_from_api_changes.py --check
check-paths.api-changelog = ^docs/architecture/migration/api-changes\.md$$|^docs/sdk/changelog-next-major\.md$$|^sdk/changelog_from_api_changes\.py$$
check-run.api-changes-gap = $(PY) sdk/api_changes_gap.py
check-paths.api-changes-gap = ^services/[^/]+/openapi\.json$$|^docs/architecture/migration/api-changes\.md$$|^sdk/api_changes_gap\.py$$

# Layer directions and database drivers only in stores (.importlinter).
check-run.lint-imports = $(LINT_IMPORTS)
check-paths.lint-imports = ^(services|packages)/.*\.py$$|^\.importlinter$$|(^|/)pyproject\.toml$$

# What's new entries and the console's own standards, with the plants that prove the second can fail.
check-run.changelog-entries = node scripts/changelog-check.mjs --entries
check-paths.changelog-entries = ^changelog/|^roadmap\.json$$|^scripts/changelog-check\.mjs$$
check-run.console-standards = node apps/console/scripts/check-standards.mjs && node apps/console/scripts/check-standards.mjs --self-test
check-paths.console-standards = ^apps/console/

# A migration whose downgrade() does nothing, beyond scripts/downgrades-waiting.txt, which only shrinks.
check-run.downgrades = $(PY) scripts/check_downgrades.py --all
check-paths.downgrades = /migrations/versions/.*\.py$$|^scripts/(check_downgrades\.py|downgrades-waiting\.txt)$$
# A migration chain with two heads (two revisions after the same one), which Alembic refuses at the deploy.
check-run.migration-heads = $(PY) scripts/check_migration_heads.py
check-paths.migration-heads = /migrations/versions/.*\.py$$|^scripts/check_migration_heads\.py$$
# A use-case script that writes outside the one output root (evidenceDir / evidence_dir, or a temp dir).
check-run.usecase-outputs = $(PY) scripts/check_usecase_outputs.py
check-paths.usecase-outputs = ^docs/usecases/.*\.(mjs|js|ts|py|sh)$$|^scripts/check_usecase_outputs\.py$$
# A test that mints a short-lived person token flakes under load; a service that imports another service, or that
# describes a shape services send each other differently from its ops_contracts class.
check-run.token-lifetime = $(PYTEST) scripts/tests/test_test_token_lifetime.py
check-paths.token-lifetime = (^|/)tests/.*\.py$$
check-run.cross-service = $(PYTEST) scripts/tests/test_no_cross_service_imports.py
check-paths.cross-service = ^services/[^/]+/(src|tests)/|^services/[^/]+/openapi\.json$$|^packages/contracts/src/|^scripts/tests/test_no_cross_service_imports\.py$$
# The code rules (environment read in one module, every route authenticated, no print or own logger): agents-service
# with its layer rules, every other service from scripts/check_service_standards.py (its WAITING list only shrinks).
check-run.standards = $(PY) services/agents-service/scripts/check_standards.py
check-paths.standards = ^(services|packages)/.*\.py$$
check-run.service-standards = $(PY) scripts/check_service_standards.py
check-paths.service-standards = ^(services|packages)/.*\.py$$|^scripts/check_service_standards\.py$$
check-run.service-standards-self-test = $(PY) scripts/check_service_standards.py --self-test
check-paths.service-standards-self-test = ^scripts/check_service_standards\.py$$
# Every list route pages and searches on the server (ListQuery or an /options page), or is on list-routes-allowlist.txt
# with its reason; the allowlist only shrinks. Read from the committed openapi.json files.
check-run.list-routes = $(PY) scripts/check_list_routes.py && $(PY) scripts/check_list_routes.py --self-test
check-paths.list-routes = ^services/[^/]+/openapi\.json$$|^list-routes-allowlist\.txt$$|^scripts/check_list_routes\.py$$

# Every /api/<service>/ path the console's clients call has a route in each gateway config (deploy/**/Caddyfile); a
# call the gateway leaves out falls through to the console and answers 404.
check-run.gateway-routes = $(PY) scripts/check_gateway_routes.py && $(PY) scripts/check_gateway_routes.py --self-test
check-paths.gateway-routes = ^deploy/.*Caddyfile$$|^deploy/compose/app\.yaml$$|^apps/console/src/lib/api/.*-http\.ts$$|^apps/console/src/lib/api/index\.ts$$|^scripts/check_gateway_routes\.py$$

# Strict types on the code and its tests: `packages` as one run, and each service through its own typecheck target. A new
# test file's untyped helper reached CI because nothing on this list type-checked tests. Pre-commit runs only the members
# whose files are staged. Code outside tests stays at zero errors; a test file may hold no more than its row in the
# member's tests-typecheck-baseline.txt (scripts/check_tests_typecheck.py), which only falls.
TYPED_SERVICES = agents-service documents-service files-service kb-service models-service platform-service runner-service tools-service
CHECK_TYPED = typecheck-packages $(addprefix typecheck-,$(TYPED_SERVICES))
CHECKS += $(CHECK_TYPED)
check-run.typecheck-packages = $(PY) scripts/check_tests_typecheck.py packages
check-paths.typecheck-packages = ^packages/.*(\.pyi?|/tests-typecheck-baseline\.txt)$$|^pyproject\.toml$$|^scripts/check_tests_typecheck\.py$$
$(foreach s,$(TYPED_SERVICES),$(eval check-run.typecheck-$(s) = $$(MAKE) -C services/$(s) typecheck))
$(foreach s,$(TYPED_SERVICES),$(eval check-paths.typecheck-$(s) = ^services/$(s)/.*\.pyi?$$$$|^services/$(s)/tests-typecheck-baseline\.txt$$$$|^scripts/check_tests_typecheck\.py$$$$|^services/$(s)/pyproject\.toml$$$$|^pyproject\.toml$$$$))

# STAGED=1 runs a check only when a staged path can change its result. STAGED_FILES names a file of staged paths, one
# a line (verify-staged.sh passes its own, read from the commit's index); unset, the index is read.
checks-staged = $(if $(STAGED_FILES),cat $(STAGED_FILES),git diff --cached --name-only --diff-filter=ACMRD)
CHECKS_FAILED = $(eval CHECKS_FAILED := $(shell mktemp -t ops-checks.XXXXXX))$(CHECKS_FAILED)
check-step = $(if $(STAGED),if $(checks-staged) | grep -qE '$(check-paths.$(1))'; then )echo "== $(1)"; $(ROOT)/scripts/keep_going.sh $(CHECKS_FAILED) $(check-run.$(1))$(if $(STAGED),; fi);

checks: ## Every check on the one list (CHECKS), each run to the end and the failures listed; STAGED=1 runs those the staged paths can change; make checks-list prints them
	@rm -f $(CHECKS_FAILED)
	@$(foreach c,$(CHECKS),$(call check-step,$(c)))
	@$(ROOT)/scripts/keep_going.sh --report $(CHECKS_FAILED)

# The checks that read history, as CI's maintainer-review job runs them after scripts/check_review_approval.py has set
# OPS_STANDARDS_REVIEW: `required` fails a rise in a baseline, `approved` passes it, `deferred` prints it as not checked.
CHECKS_HISTORY = access-exceptions-commits portable-store-commits config-literals-commits typed-boundaries-commits console-baselines-commits \
  tests-typecheck-commits ratchet-history
# The review is the one given, else the one GitHub holds for this branch's pull request (`required` when it cannot be
# read), so a rise fails here unless a maintainer approved it. `make verify` runs this too.
checks-history: export OPS_STANDARDS_REVIEW = $(or $(REVIEW_GIVEN),$(shell $(PY) scripts/check_review_approval.py --local))
checks-history: ## The history checks alone, for the pull request's review job (OPS_STANDARDS_REVIEW=required|approved)
	@rm -f $(CHECKS_FAILED)
	@$(foreach c,$(CHECKS_HISTORY),echo "== $(c)"; $(ROOT)/scripts/keep_going.sh $(CHECKS_FAILED) $(check-run.$(c));)
	@$(ROOT)/scripts/keep_going.sh --report $(CHECKS_FAILED)

# Every `run:` step in ci.yml has a local twin or a stated reason it has none (scripts/ci_steps.json).
check-run.ci-steps = $(PY) scripts/ci_steps.py --check
check-paths.ci-steps = ^\.github/workflows/ci\.yml$$|^scripts/ci_steps\.(py|json)$$
check-run.ci-steps-self-test = $(PY) scripts/ci_steps.py --self-test
check-paths.ci-steps-self-test = ^scripts/ci_steps\.py$$

# The jobs CI would run for this change (scripts/ci-plan.sh + ci.yml), side by side, each on its own database and ports.
check-run.staging-hold-tests = $(PYTEST) scripts/tests/test_staging_hold.py
check-paths.staging-hold-tests = ^scripts/(staging_hold\.py|tests/test_staging_hold\.py)$$|^\.github/workflows/deploy-staging\.yml$$
check-run.quarantine = $(PY) scripts/quarantine.py check
check-paths.quarantine = ^config/quarantine\.json$$|^scripts/quarantine\.py$$
check-run.quarantine-self-test = $(PY) scripts/quarantine.py --self-test
check-paths.quarantine-self-test = ^scripts/quarantine\.py$$
check-run.ci-usecases-self-test = $(PY) scripts/ci_usecases.py --self-test
check-paths.ci-usecases-self-test = ^scripts/(ci_usecases|quarantine)\.py$$|^scripts/agents/(affected_usecases\.py|usecase_map\.json)$$
check-run.ci-local-self-test = $(PY) scripts/ci_local.py --self-test
check-paths.ci-local-self-test = ^scripts/ci_local\.py$$|^\.github/workflows/ci\.yml$$

check-run.new-migration-self-test = $(PY) scripts/new_migration.py --self-test
check-paths.new-migration-self-test = ^scripts/new_migration\.py$$
check-run.pr-flow-self-test = $(PY) scripts/pr_flow.py --self-test
check-paths.pr-flow-self-test = ^scripts/pr_flow\.py$$
check-run.lane-self-test = bash scripts/lane.sh --self-test
check-paths.lane-self-test = ^scripts/lane\.sh$$
check-run.builder-watch-self-test = bash scripts/builder-watch.sh --self-test
check-paths.builder-watch-self-test = ^scripts/builder-watch\.sh$$

ci-local: db-up ## CI's planned jobs run here in parallel (BASE=origin/develop, JOBS=<cores/2>, JOB=a,b job names or labels, FULL=1, PLAN=1; OUT=<file>.json result; RERUN=<file>.json only its red jobs; SHARDS=n SHARD=i; UCS="uc-1:api uc-2" adds use cases); exit 1 on any failure
	@uv run python scripts/ci_local.py --base "$(or $(BASE),origin/develop)" $(if $(JOBS),--jobs $(JOBS)) $(if $(JOB),--job "$(JOB)") $(if $(FULL),--full) $(if $(PLAN),--plan) $(if $(OUT),--out "$(OUT)") $(if $(RERUN),--rerun "$(RERUN)") $(if $(SHARDS),--shards $(SHARDS) --shard $(or $(SHARD),1)) $(if $(UCS),--uc $(UCS))

checks-list: ## Print each check on the list with the command it runs
	@$(foreach c,$(CHECKS),printf '%s\t%s\n' '$(c)' '$(check-run.$(c))';)

gha-verify: ## The full `make verify` on GitHub for BRANCH (verify-full.yml): start it, watch it, print the first error line of each failed job; exit 1 when red
	@test -n "$(BRANCH)" || { echo "usage: make gha-verify BRANCH=<branch>"; exit 2; }
	@python3 $(ROOT)/scripts/pr_flow.py verify --branch "$(BRANCH)"

requeue: ## Pull request PR=N: out of the merge queue, then back in at the end once its checks pass (after a fix pushed to a queued branch)
	@test -n "$(PR)" || { echo "usage: make requeue PR=<number>"; exit 2; }
	@bash $(ROOT)/scripts/requeue.sh "$(PR)"
