# PostgreSQL and OPA from deploy/compose, and the agents service's Alembic migrations (the only migrations so far;
# the tools service shares that schema until migrations split per service).
.PHONY: db-up db-down db-shell db-reset db-sweep db-move-image migrate migration

##@ Database

db-up: ## PostgreSQL, OPA and the test mail servers (GreenMail, Mailpit) in compose, waiting until up
ifeq ($(OPS_INFRA),external)
	@echo "OPS_INFRA=external: postgres, opa, greenmail and mailpit are side containers"
else
	@# --no-recreate: every checkout, worktree and verify export shares this compose project, and its OPA mounts the
	@# policy folder by path; recreating from another checkout re-mounts OPA there and drops the review key the running
	@# tools-service loaded. A changed compose file therefore needs `docker compose ... up -d --force-recreate`.
	$(COMPOSE) up -d --wait --no-recreate postgres opa greenmail mailpit
endif

db-down: ## Stop compose; the data volume stays
ifeq ($(OPS_INFRA),external)
	@echo "OPS_INFRA=external: leaving side containers running"
else
	$(COMPOSE) down
endif

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

db-move-image: ## Move the stack's database onto the compose file's PostgreSQL image: dump, a fresh volume, restore; asks first
	@# The pgvector image is Debian (glibc) where the old one was Alpine (musl): the two sort text differently, so the
	@# old data folder is never reused (its text indexes would be wrong). The old volume is left as it was.
	@# The restore log's two "already exists" errors (the role ops and the database ops_runtime, which the new image
	@# makes at start) are expected; the rest restores into them.
	@if [ "$(CONFIRM)" != yes ]; then \
		printf 'Dump every database on the stack PostgreSQL, recreate it on the compose image and restore? Type yes: '; read answer; \
		[ "$$answer" = yes ] || { echo "db-move-image: nothing changed"; exit 1; }; \
	fi
	@mkdir -p $(OPS_DATA_DIR)/db-dumps
	@dump=$(OPS_DATA_DIR)/db-dumps/pg-$$(date +%Y%m%d-%H%M%S).sql; \
	  echo "db-move-image: dumping to $$dump"; \
	  $(COMPOSE) exec -T postgres pg_dumpall -U ops > "$$dump" || { echo "db-move-image: the dump failed; nothing changed"; exit 1; }; \
	  $(STACK) stop-for-reset; \
	  $(COMPOSE) stop postgres && $(COMPOSE) rm -f postgres && \
	  $(COMPOSE) up -d --wait postgres && \
	  $(COMPOSE) exec -T postgres psql -q -U ops -d postgres -v ON_ERROR_STOP=0 < "$$dump" > $(OPS_DATA_DIR)/db-dumps/restore.log 2>&1; \
	  echo "db-move-image: restored from $$dump (log: $(OPS_DATA_DIR)/db-dumps/restore.log); run make up"
