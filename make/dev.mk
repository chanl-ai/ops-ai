# The local stack: compose (PostgreSQL, OPA), migrations, then the agents service, tools service and console in the
# background. scripts/stack.sh is the process manager: logs in .logs/<svc>.log, pids in .run/<svc>.pid.
.PHONY: up down restart health logs ports

##@ Stack (ISOLATED=1 for a second stack)

up: db-up ## Compose, rebuild or migrate the database, then platform, agents, tools and console; KEEP_DATA=1 migrates in place; AUTH=platform signs in through platform-service
	@# Services started before their code last changed run old code: stopped here, started again after the schema step.
	@$(STACK) stop-stale
	@# Before launch there is no data to keep: a database this code did not build is rebuilt from the chains, and
	@# the dev seeds refill it on start. KEEP_DATA=1 migrates in place instead (scripts/schema_sync.py).
	@if [ "$(KEEP_DATA)" != "1" ]; then \
		rc=0; uv run --quiet --project $(ROOT) python $(ROOT)/scripts/schema_sync.py "$(OPS_DATABASE_URL)" || rc=$$?; \
		if [ $$rc -eq 3 ]; then $(STACK) stop-for-reset && uv run --quiet --project $(ROOT) python $(ROOT)/scripts/schema_sync.py "$(OPS_DATABASE_URL)" --reset; \
		elif [ $$rc -ne 0 ]; then exit $$rc; fi; \
	fi
	@$(MAKE) -s migrate
	@$(STACK) up
	@$(STACK) health

down: ## Stop what `make up` started, then compose (KEEP_DB=1 leaves compose running)
	@$(STACK) down
	@if [ "$(KEEP_DB)" != "1" ]; then $(MAKE) -s db-down; fi

restart: ## Restart the services `make up` started (SVC=agents|tools|platform|console for one), migrating each first
	@# Each service's chain is applied between stop and start, as make up does, so a restart of newer code never
	@# meets a table without its new columns. The console has no database.
	@if [ -n "$(SVC)" ]; then \
		$(STACK) stop $(SVC) && \
		{ [ "$(SVC)" = console ] || $(MAKE) -s -C $(SVC_DIR_$(SVC)) migrate; } && \
		$(STACK) start $(SVC); \
	else \
		$(STACK) down && \
		for d in $(SVC_DIR_agents) $(SVC_DIR_tools) $(SVC_DIR_models) $(SVC_DIR_platform); do $(MAKE) -s -C $$d migrate || exit 1; done && \
		$(STACK) up; \
	fi
	@$(STACK) health $(SVC)

health: ## Probe every service, OPA and PostgreSQL; shows port, state and who owns the listener
	@$(STACK) health

logs: ## Follow one service's log: make logs SVC=agents|tools|console (FOLLOW=0 to print and exit)
	@OPS_LOGS_FOLLOW=$(if $(FOLLOW),$(FOLLOW),1) $(STACK) logs $(SVC)

ports: ## Print the ports this stack uses
	@printf '  stack %s, compose project %s\n' "$(OPS_STACK)" "$(OPS_COMPOSE_PROJECT)"
	@printf '  console %s (runtime %s), agents %s, tools %s, opa %s, postgres %s\n' $(OPS_CONSOLE_PORT) \
		$(OPS_CONSOLE_RUNTIME_PORT) $(OPS_AGENTS_PORT) $(OPS_TOOLS_PORT) $(OPS_OPA_PORT) $(OPS_PG_PORT)
