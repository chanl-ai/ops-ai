# PostgreSQL and OPA from deploy/compose, and the agents service's Alembic migrations (the only migrations so far;
# the tools service shares that schema until migrations split per service).
.PHONY: db-up db-down db-shell db-reset migrate migration

##@ Database

db-up: ## PostgreSQL and OPA in compose, waiting until healthy
	@# --no-recreate: every checkout, worktree and verify export shares this compose project, and its OPA mounts the
	@# policy folder by path; recreating from another checkout re-mounts OPA there and drops the review key the running
	@# tools-service loaded. A changed compose file therefore needs `docker compose ... up -d --force-recreate`.
	$(COMPOSE) up -d --wait --no-recreate postgres opa

db-down: ## Stop compose (data volume kept)
	$(COMPOSE) down

db-shell: ## psql into the stack's database
	$(COMPOSE) exec postgres psql -U ops -d ops_runtime

db-reset: ## Drop the data volume and migrate from empty (asks first; CONFIRM=yes skips the question)
	@if [ "$(CONFIRM)" != "yes" ]; then \
		printf 'Delete every row in compose project %s? [y/N] ' "$(OPS_COMPOSE_PROJECT)"; read ans; \
		[ "$$ans" = "y" ] || { echo "kept"; exit 1; }; fi
	$(COMPOSE) down -v
	$(MAKE) -s db-up migrate

migrate: ## Apply every service's own migration chain to head (agents, tools, models, platform)
	@# A service still running older code breaks when newer migrations change its tables under it.
	@$(STACK) check-fresh || { echo "migrate refused: a running service is older than its code; run make up"; exit 1; }
	$(MAKE) -C $(SVC_DIR_agents) migrate
	$(MAKE) -C $(SVC_DIR_tools) migrate
	$(MAKE) -C $(SVC_DIR_models) migrate
	$(MAKE) -C services/platform-service migrate

migration: ## New Alembic revision: make migration NAME="add case table"
	@test -n "$(NAME)" || { echo 'usage: make migration NAME="what it changes"'; exit 2; }
	cd $(SVC_DIR_agents) && uv run alembic revision -m "$(NAME)"
