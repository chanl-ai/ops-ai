# Ops AI. The root Makefile only orchestrates: it includes make/*.mk by concern and delegates to each service's own
# Makefile with $(MAKE) -C. Strategy and the daily commands: docs/architecture/make.md. `make help` lists the targets.
.DEFAULT_GOAL := help
.PHONY: help install verify clean

include make/env.mk
include make/dev.mk
include make/db.mk
include make/db-scripts.mk
include make/release.mk
include make/staging.mk
include make/services.mk
include make/console.mk
include make/python.mk
include make/deps.mk
include make/docs.mk
include make/sdk.mk
include make/usecase.mk
include make/experiments.mk

##@ General

help: ## List targets (add ISOLATED=1 to any stack target for a second stack on ports +1000)
	@awk "$$HELP_AWK" $(MAKEFILE_LIST)
	@printf '\nPer service (generated; SERVICES=%s)\n' "$(SERVICES)"
	@printf '  %-20s %s\n' "<verb>-<svc>" "make -C <svc dir> <verb>; verbs: $(SERVICE_VERBS)"

install: console-install python-install ## Install the console and the Python workspace

verify: console-verify docs-verify python-verify sdk-verify changelog-verify ## Everything a commit must pass (scripted model only)

changelog-verify: ## What's new entries and Coming next items are written for a person using the console (c-510)
	node scripts/changelog-check.mjs --entries
	node scripts/changelog-check.mjs --self-test >/dev/null

clean: ## Remove logs, pids and caches (stop the stack first)
	rm -rf .logs .run .ruff_cache .pytest_cache
	@$(foreach s,$(SERVICES),$(MAKE) -s -C $(SVC_DIR_$(s)) clean;)
