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
	@# old data folder is never reused (its text indexes would be wrong). The old volume (ops-runtime-pg) is left as it
	@# was: rolling back is pointing the compose file's volume and image at it again. scripts/db-move-image.sh counts
	@# every table's rows before and after, refuses a dump short of them, and stops the restore at its first error.
	@if [ "$(CONFIRM)" != yes ]; then \
		printf 'Dump every database on the stack PostgreSQL, recreate it on the compose image and restore? Type yes: '; read answer; \
		[ "$$answer" = yes ] || { echo "db-move-image: nothing changed"; exit 1; }; \
	fi
	@mkdir -p $(OPS_DATA_DIR)/db-dumps
	@dump=$(OPS_DATA_DIR)/db-dumps/pg-$$(date +%Y%m%d-%H%M%S).sql; \
	  export PG_EXEC="$(COMPOSE) exec -T postgres"; move=$(ROOT)/scripts/db-move-image.sh; \
	  $$move rows > $$dump.before || { echo "db-move-image: could not count rows; nothing changed"; exit 1; }; \
	  echo "db-move-image: rows per database before"; awk '{ n[$$1] += $$3 } END { for (d in n) print "  " d, n[d] }' $$dump.before | sort; \
	  echo "db-move-image: dumping to $$dump"; \
	  $$move dump $$dump $$dump.before || { echo "db-move-image: nothing changed"; exit 1; }; \
	  $(STACK) stop-for-reset; \
	  $(COMPOSE) stop postgres && $(COMPOSE) rm -f postgres && \
	  $(COMPOSE) up -d --wait postgres && \
	  $$move restore $$dump > $(OPS_DATA_DIR)/db-dumps/restore.log 2>&1 || \
	    { echo "db-move-image: the restore stopped (log: $(OPS_DATA_DIR)/db-dumps/restore.log); the old volume ops-runtime-pg is untouched"; exit 1; }; \
	  $$move rows > $$dump.after; \
	  echo "db-move-image: rows per database after"; awk '{ n[$$1] += $$3 } END { for (d in n) print "  " d, n[d] }' $$dump.after | sort; \
	  if diff $$dump.before $$dump.after; then echo "db-move-image: every table has the rows it had"; \
	  else echo "db-move-image: the tables above differ; the old volume ops-runtime-pg is untouched"; exit 1; fi; \
	  echo "db-move-image: restored from $$dump (log: $(OPS_DATA_DIR)/db-dumps/restore.log); run make up"
