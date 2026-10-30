# Use-case tests: the central API, SDK, CLI and UI checks (docs/usecases/README.md). Each service keeps its own unit
# tests; these targets only call scripts/usecase.mjs, which runs one script per use case and layer. Scripts start the
# agents service on the scripted model on their own ports, so no target here makes a real model call unless
# APPROVED_REAL_CALLS=<n> is set.
.PHONY: usecase-test usecase-report usecase-list usecase-show usecase-coverage usecase-new usecase-runner-test usecase-reset

# Each run picks free ports and creates its own database (ops_usecase_r<pid>_<hex>), dropped when it ends, so runs
# from different sessions never collide. OPS_USECASE_{AGENTS,TOOLS,MODELS,CONSOLE}_PORT and OPS_USECASE_DB set in the
# environment or on the command line are used as given; nothing is defaulted here.

USECASE := node $(ROOT)/scripts/usecase.mjs

##@ Use cases

# At most USECASE_SLOTS runs on this Mac at once (each starts its own stack); the rest wait for a slot.
USECASE_SLOTS ?= 3
usecase-test-run = python3 scripts/at-most.py $(USECASE_SLOTS) usecase -- $(USECASE)
usecase-test: ## Run use cases: make usecase-test UC=<id> LAYER=api|sdk|cli|ui (both optional; needs make db-up)
	@$(usecase-test-run) test $(if $(UC),--uc $(UC)) $(if $(LAYER),--layer $(LAYER))

usecase-report: ## Each use case's stories, works or broken, from its latest runs: make usecase-report UC=<id> (all with stories when unset)
	@$(USECASE) report $(if $(UC),--uc $(UC))

usecase-list: ## List the use case registry
	@$(USECASE) list

usecase-show: ## One use case and its script per layer: make usecase-show UC=<id>
	@$(USECASE) show $(UC)

usecase-coverage: ## Scripts per layer for a service: make usecase-coverage SERVICE=agents-service (all when unset)
	@$(USECASE) coverage $(SERVICE)

usecase-new: ## Register a use case: make usecase-new SERVICE=<service> TITLE="<title>"
	@$(USECASE) new $(SERVICE) "$(TITLE)"

usecase-reset: ## Drop runner-made use-case databases, including ones a killed run left (a pinned OPS_USECASE_DB is yours)
	@printf '%s\n' "SELECT format('DROP DATABASE %I WITH (FORCE)', datname) FROM pg_database WHERE datname ~ '^ops_usecase(_isolated|_r[0-9]+_[0-9a-f]{6})?$$'" '\gexec' \
	  | $(COMPOSE) exec -T postgres psql -U ops -d postgres -q

usecase-runner-test: ## Type-check and test packages/usecase-runner
	pnpm --filter @ops-ai/usecase-runner verify
