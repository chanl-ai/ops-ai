# PostgreSQL and OPA from deploy/compose, and the agents service's Alembic migrations (the only migrations so far;
# the tools service shares that schema until migrations split per service).
.PHONY: db-up db-down db-shell db-reset db-sweep migrate migration

##@ Database

db-up: ## PostgreSQL, OPA and the test mail servers (GreenMail, Mailpit) in compose, waiting until up
	@# --no-recreate: every checkout, worktree and verify export shares this compose project, and its OPA mounts the
	@# policy folder by path; recreating from another checkout re-mounts OPA there and drops the review key the running
	@# tools-service loaded. A changed compose file therefore needs `docker compose ... up -d --force-recreate`.
	$(COMPOSE) up -d --wait --no-recreate postgres opa greenmail mailpit

db-down: ## Stop compose (the shared stack keeps its data volume; ISOLATED=1 removes its own)
	@# An isolated stack is one session's: its volume goes with it, so a day of isolated runs does not fill the disk.
	$(COMPOSE) down $(if $(filter isolated,$(OPS_STACK)),--volumes)

db-sweep: ## Drop scratch databases of runs that are over (dead pid, no session); DRY_RUN=1 lists them
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/scratch_db_sweep.py $(if $(DRY_RUN),--dry-run)

db-shell: ## psql into the stack's database
	$(COMPOSE) exec postgres psql -U ops -d ops_runtime

db-reset: ## The same as make reset-db (kept so old commands work)
	@$(MAKE) -s reset-db

migrate: ## Apply every service's own migration chain to head (agents, tools, models, kb, platform, files, documents)
	@# A service still running older code breaks when newer migrations change its tables under it.
	@$(STACK) check-fresh || { echo "migrate refused: a running service is older than its code or the last migration; run make up"; exit 1; }
	$(MAKE) -C $(SVC_DIR_agents) migrate
	$(MAKE) -C $(SVC_DIR_tools) migrate
	$(MAKE) -C $(SVC_DIR_models) migrate
	$(MAKE) -C $(SVC_DIR_kb) migrate
	$(MAKE) -C services/platform-service migrate
	$(MAKE) -C services/files-service migrate
	$(MAKE) -C services/documents-service migrate
	@# Every process started before a migration landed is stale from here (stack.sh note-migrations, fb-16aa519c).
	@$(STACK) note-migrations

migration: ## New Alembic revision: make migration NAME="add case table"
	@test -n "$(NAME)" || { echo 'usage: make migration NAME="what it changes"'; exit 2; }
	cd $(SVC_DIR_agents) && uv run alembic revision -m "$(NAME)"
