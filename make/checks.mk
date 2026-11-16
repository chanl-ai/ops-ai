# The one list of checks. `make verify` (through python-verify), the pull-request `checks` job in ci.yml, the push
# check in verify-changed.sh and pre-commit (`make checks STAGED=1`) all run `make checks`, so a check added here runs
# in every one of them and none can run a shorter list. A check is a name in CHECKS, the command that runs it and, for
# pre-commit, the staged paths that can change its result. Each is proven red by its own test or `--self-test`.
.PHONY: checks checks-list

##@ Checks

# The interpreter and tools each check runs on. verify-staged.sh points them at the checkout's own environment, since a
# `uv run` inside the export of a commit would install every member again.
PY ?= uv run python
PYTEST ?= $(PY) -m pytest -q -p no:cacheprovider
LINT_IMPORTS ?= uv run lint-imports --no-logo

CHECKS = \
  access-exceptions access-exceptions-commits access-exceptions-self-test \
  portable-store portable-store-commits \
  config-literals config-literals-commits \
  typed-boundaries \
  isolation-markings isolation-sites \
  store-inventory roles-matrix sbom k8s-base \
  lint-imports sdk-drift changelog-entries console-standards

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

# Every table marked and indexed; the raw transaction, savepoint, relay and loop-health sites each service still holds.
check-run.isolation-markings = $(PYTEST) deploy/database/tests/test_isolation_markings.py deploy/database/tests/test_indexes.py
check-paths.isolation-markings = ^deploy/database/|^(services|packages)/[^/]+/(src|migrations)/
check-run.isolation-sites = $(PYTEST) packages/ops_store/tests/test_isolation_sites.py packages/ops_store/tests/test_relay_sites.py packages/ops_store/tests/test_loop_health.py
check-paths.isolation-sites = ^packages/ops_store/|^(services|packages)/[^/]+/(src|tests)/.*\.py$$

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

# Layer directions and database drivers only in stores (.importlinter).
check-run.lint-imports = $(LINT_IMPORTS)
check-paths.lint-imports = ^(services|packages)/.*\.py$$|^\.importlinter$$|(^|/)pyproject\.toml$$

# What's new entries and the console's own standards, with the plants that prove the second can fail.
check-run.changelog-entries = node scripts/changelog-check.mjs --entries
check-paths.changelog-entries = ^changelog/|^roadmap\.json$$|^scripts/changelog-check\.mjs$$
check-run.console-standards = node apps/console/scripts/check-standards.mjs && node apps/console/scripts/check-standards.mjs --self-test
check-paths.console-standards = ^apps/console/

# STAGED=1 runs a check only when a staged path can change its result. STAGED_FILES names a file of staged paths, one
# a line (verify-staged.sh passes its own, read from the commit's index); unset, the index is read.
checks-staged = $(if $(STAGED_FILES),cat $(STAGED_FILES),git diff --cached --name-only --diff-filter=ACMRD)
CHECKS_FAILED = $(eval CHECKS_FAILED := $(shell mktemp -t ops-checks.XXXXXX))$(CHECKS_FAILED)
check-step = $(if $(STAGED),if $(checks-staged) | grep -qE '$(check-paths.$(1))'; then )echo "== $(1)"; $(ROOT)/scripts/keep_going.sh $(CHECKS_FAILED) $(check-run.$(1))$(if $(STAGED),; fi);

checks: ## Every check on the one list (CHECKS), each run to the end and the failures listed; STAGED=1 runs those the staged paths can change; make checks-list prints them
	@rm -f $(CHECKS_FAILED)
	@$(foreach c,$(CHECKS),$(call check-step,$(c)))
	@$(ROOT)/scripts/keep_going.sh --report $(CHECKS_FAILED)

checks-list: ## Print each check on the list with the command it runs
	@$(foreach c,$(CHECKS),printf '%s\t%s\n' '$(c)' '$(check-run.$(c))';)
