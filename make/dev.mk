# The local stack: compose (PostgreSQL, OPA), migrations, then the agents service, tools service and console in the
# background. scripts/stack.sh is the process manager: logs in .logs/<svc>.log, pids in .run/<svc>.pid.
.PHONY: up down restart reset-db health logs ports demo-model sample-team demo-walk demo

##@ Stack (ISOLATED=1 for a second stack)

DEMO_MODEL ?= gpt-5-mini
# The guardrail checks and memory extraction: a non-reasoning model, so a check takes about a second rather than five
# and a reply's end does not wait on a slow extraction (owner, 2026-10-18).
# The chat alias the agents name stays on gpt-5-nano: gpt-4.1-mini answered without calling load_skill, so an agent's
# skill was never read (seed-walk check a). DEMO_MODEL stays on `default`, which reads documents. The three share one
# provider connection, so DEMO_MODEL=fake puts all of them on the fake.
DEMO_FAST_MODEL ?= $(if $(filter fake,$(DEMO_MODEL)),fake,gpt-4.1-mini)
DEMO_CHAT_MODEL ?= $(if $(filter fake,$(DEMO_MODEL)),fake,gpt-5-nano)

up: db-up ## Compose, migrate every chain in place, then the services, the worker, models-service and the demo fakes; AUTH=platform signs in through platform-service; RESET=1 wipes the database first (as make reset-db); OPS_INFRA=external uses side containers and skips db-up/db-down
	@# Services started before their code last changed run old code: stopped here, started again after the schema step.
	@$(STACK) stop-stale
	@# Always migrate, never drop data on its own (owner, c-099). A chain the database holds ahead of this checkout
	@# stops here with the chain named; only RESET=1 or make reset-db wipes. KEEP_DATA=1 is accepted and changes nothing.
	@if [ "$(RESET)" = "1" ]; then $(MAKE) -s reset-db; fi
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/schema_sync.py "$(OPS_DATABASE_URL)" || { \
		echo "make up stopped: the database is ahead of this checkout (above). Nothing was changed."; exit 1; }
	@$(MAKE) -s migrate || { echo "make up stopped: a migration failed (above). The database keeps what applied; fix the migration or run make reset-db."; exit 1; }
	@# The first admin, through platform-service's bootstrap: its password is kept in .run/dev-admin.env for make sample-team.
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/dev_admin.py
	@# A migration that just landed makes every process started before it stale: stopped here, started below.
	@$(STACK) stop-stale
	@$(STACK) up
	@# The dev mail and bank fakes answer at this machine's private address, which moves with the network; the
	@# shared stack's egress list is brought up to date with it so mail and bank calls are not refused after a move.
	@if [ "$(OPS_STACK)" = shared ]; then uv run --quiet --project $(ROOT) python $(ROOT)/scripts/dev_egress.py; fi
	@# The shared stack's agents and workflow reads run on a real OpenAI model (owner, 2026-10-18; DEMO_MODEL picks it,
	@# DEMO_MODEL=fake keeps the fake). Use cases and tests run on their own stacks and keep the fake.
	@if [ "$(OPS_STACK)" = shared ]; then \
		MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=guardrail-check MODEL=$(DEMO_FAST_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=gpt-5.5 MODEL=$(DEMO_CHAT_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=memory-extract MODEL=$(DEMO_FAST_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=extract MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py; fi
	@$(STACK) health

reset-db: ## Wipe the stack's database and rebuild it empty from the chains; asks first on the shared stack (CONFIRM=yes skips)
	@# Refused while the recipe is expanded, so before anything runs and even under make -n: an isolated stack that
	@# would drop the shared database has taken the shared stack's address from somewhere.
	$(if $(and $(filter isolated,$(OPS_STACK)),$(or $(findstring $(SHARED_DATABASE),$(OPS_DATABASE_URL)),$(findstring 127.0.0.1:5477/ops_runtime,$(OPS_DATABASE_URL)))),$(error reset-db refused: ISOLATED=1 would drop the shared stack's database ($(OPS_DATABASE_URL))))
	@if [ "$(OPS_STACK)" = shared ] && [ "$(CONFIRM)" != yes ]; then \
		printf 'Wipe %s for every session on the shared stack? Type yes: ' "$(OPS_DATABASE_URL)"; read answer; \
		[ "$$answer" = yes ] || { echo "reset-db: nothing changed"; exit 1; }; \
	fi
	@$(STACK) stop-for-reset
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/schema_sync.py "$(OPS_DATABASE_URL)" --reset
	@$(MAKE) -s migrate

down: ## Stop what `make up` started, then compose (KEEP_DB=1 leaves compose running)
	@$(STACK) down
	@if [ "$(KEEP_DB)" != "1" ]; then $(MAKE) -s db-down; fi

restart: ## Restart the services `make up` started (SVC=agents|worker|tools|kb|files|platform|console for one), migrating each first
	@# Each service's chain is applied between stop and start, as make up does, so a restart of newer code never
	@# meets a table without its new columns. The console, the embed app, the API docs page and the runner have no
	@# database; the worker uses agents-service's.
	@if [ -n "$(SVC)" ]; then \
		$(STACK) stop $(SVC) && \
		{ case "$(SVC)" in console|worker|embed|apidocs|runner) ;; *) $(MAKE) -s -C $(SVC_DIR_$(SVC)) migrate && $(STACK) note-migrations;; esac; } && \
		$(STACK) start $(SVC); \
	else \
		$(STACK) down && \
		for d in $(SVC_DIR_agents) $(SVC_DIR_tools) $(SVC_DIR_models) $(SVC_DIR_kb) $(SVC_DIR_platform) $(SVC_DIR_files) $(SVC_DIR_documents); do $(MAKE) -s -C $$d migrate || exit 1; done && \
		$(STACK) note-migrations && $(STACK) up; \
	fi
	@$(STACK) health $(SVC)

health: ## Probe every service, OPA and PostgreSQL; shows port, state and who owns the listener
	@$(STACK) health

sample-team: ## Install the sample team (scripts/sample-team/sample-team.json) as the first admin; a second run finds it (NAME= another team, EXPECT_FOUND=1 fails on anything made)
	@MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_team.py install $(if $(NAME),--name "$(NAME)") $(if $(EXPECT_FOUND),--expect-found)

logs: ## Follow one service's log: make logs SVC=agents|tools|runner|console (FOLLOW=0 to print and exit)
	@OPS_LOGS_FOLLOW=$(if $(FOLLOW),$(FOLLOW),1) $(STACK) logs $(SVC)

runner-wasm: ## Fetch the code runner's pinned Python build into .data/runner and check its SHA-256 (make up does it too)
	@$(MAKE) -s -C services/runner-service wasm

demo-walk: ## Walk the sample team: chat, guardrail, bank reads, a write a person approves, then an emailed levy notice to the second reply (PASS/FAIL each; re-runnable)
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_walk.py $(if $(NAME),--name "$(NAME)")

demo: sample-team demo-walk ## Install the sample team, then walk it

demo-model: ## Point the agents' chat alias at a cheap real OpenAI model (MODEL=gpt-5-nano), or back at the fake (MODEL=fake)
	@MODEL=$(MODEL) uv run python scripts/demo_model.py

ports: ## Print the ports this stack uses
	@printf '  stack %s, compose project %s\n' "$(OPS_STACK)" "$(OPS_COMPOSE_PROJECT)"
	@printf '  console %s (runtime %s), agents %s, tools %s, opa %s, postgres %s\n' $(OPS_CONSOLE_PORT) \
		$(OPS_CONSOLE_RUNTIME_PORT) $(OPS_AGENTS_PORT) $(OPS_TOOLS_PORT) $(OPS_OPA_PORT) $(OPS_PG_PORT)
