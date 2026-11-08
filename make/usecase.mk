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

uc-impacted: ## The core UI use cases plus the ones the change since BASE touches, in two shards, on HEAD's export (the plugins checkout beside the repo, or OPS_PLUGINS_REPO): make uc-impacted [BASE=origin/main] [MAX=8]
	@python3 scripts/uc_impacted.py --base $(or $(BASE),origin/main) $(if $(MAX),--max $(MAX))
	@ids="$$(python3 scripts/uc_impacted.py --base $(or $(BASE),origin/main) $(if $(MAX),--max $(MAX)) --ids)"; \
	  set -- $$ids; a=""; b=""; i=0; for u in "$$@"; do if [ $$((i % 2)) -eq 0 ]; then a="$$a $$u"; else b="$$b $$u"; fi; i=$$((i + 1)); done; \
	  out=$${UC_OUT:-/tmp/uc-impacted}; mkdir -p "$$out"; \
	  run() { OPS_PLUGINS_REPO="$${OPS_PLUGINS_REPO:-$(abspath $(STACK_HOME)/../ops-ai-plugins)}" QA_RUNNER=1 VERIFY_RUN="rc=0; for u in $$1; do make -s usecase-test LAYER=ui UC=\$$u || rc=1; done; exit \$$rc" scripts/verify-head.sh > "$$2" 2>&1; }; \
	  run "$$a" "$$out/shard1.log" & p1=$$!; run "$$b" "$$out/shard2.log" & p2=$$!; wait $$p1; r1=$$?; wait $$p2; r2=$$?; \
	  grep -hE '^(FAIL|PASS|ok) +uc-[0-9]+ ui' "$$out"/shard*.log; echo "logs: $$out"; [ $$r1 -eq 0 ] && [ $$r2 -eq 0 ]
