# The local stack: compose (PostgreSQL, OPA), migrations, then the agents service, tools service and console in the
# background. scripts/stack.sh is the process manager: logs in .logs/<svc>.log, pids in .run/<svc>.pid.
.PHONY: up down restart reset-db health logs ports demo-model sample-team sample-library sample-teams demo-walk demo demo-salesforce demo-salesforce-templates demo-salesforce-walk

##@ Stack (one per machine)

# With no OPENAI_API_KEY there is no real model to reach, so the stack stays on the fake one.
DEMO_MODEL ?= $(if $(OPENAI_API_KEY),gpt-5-mini,fake)
# The guardrail checks and memory extraction: a non-reasoning model, so a check takes about a second rather than five
# and a reply's end does not wait on a slow extraction.
# The chat alias the agents name stays on gpt-5-nano: gpt-4.1-mini answered without calling load_skill, so an agent's
# skill was never read (seed-walk check a). DEMO_MODEL stays on `default`, which reads documents. The three share one
# provider connection, so DEMO_MODEL=fake puts all of them on the fake.
DEMO_FAST_MODEL ?= $(if $(filter fake,$(DEMO_MODEL)),fake,gpt-4.1-mini)
DEMO_CHAT_MODEL ?= $(if $(filter fake,$(DEMO_MODEL)),fake,gpt-5-nano)

up: db-up ## Compose, migrate every chain in place, then the services, the worker, models-service and the demo fakes; AUTH=platform signs in through platform-service; RESET=1 wipes the database first (as make reset-db); a new database gets the sample team (SAMPLE=0 skips); OPS_INFRA=external uses side containers and skips db-up/db-down
	@# Services started before their code last changed run old code: stopped here, started again after the schema step.
	@$(STACK) stop-stale
	@# Always migrate, never drop data on its own. A chain the database holds ahead of this checkout
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
	@$(MAKE) -s plugins-check
	@# The dev mail and bank fakes answer at this machine's private address, which moves with the network; the
	@# egress list is brought up to date with it so mail and bank calls are not refused after a move.
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/dev_egress.py
	@# The stack's agents and workflow reads run on a real OpenAI model (DEMO_MODEL picks it, DEMO_MODEL=fake keeps
	@# the fake). Use cases and tests start their own services and keep the fake. An alias an admin pointed at their
	@# own model in the console is left there (KEEP_ADMIN_CHOICE).
	@{ export KEEP_ADMIN_CHOICE=1; \
		MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=guardrail-check MODEL=$(DEMO_FAST_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=gpt-5.5 MODEL=$(DEMO_CHAT_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=memory-extract MODEL=$(DEMO_FAST_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py && \
		ALIAS=extract MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_model.py; }
	@$(STACK) health
	@# A new database gets the sample team once, so a fresh clone has people, knowledge and agents to try; the marker
	@# goes with the database (make reset-db removes it). SAMPLE=0 skips it.
	@if [ "$(SAMPLE)" != "0" ] && [ ! -f "$(OPS_RUN_DIR)/sample-team.installed" ]; then \
		$(MAKE) -s sample-team && touch "$(OPS_RUN_DIR)/sample-team.installed"; \
	fi
	@# The demo policy library, once per database, in team Platform where the signed-in dev admin sees it.
	@if [ "$(SAMPLE)" != "0" ] && [ ! -f "$(OPS_RUN_DIR)/sample-library.installed" ]; then \
		$(MAKE) -s sample-library && touch "$(OPS_RUN_DIR)/sample-library.installed"; \
	fi

reset-db: ## Wipe the stack's database and rebuild it empty from the chains; asks first (CONFIRM=yes skips)
	@if [ "$(CONFIRM)" != yes ]; then \
		printf 'Wipe %s, which every checkout of this machine shares? Type yes: ' "$(OPS_DATABASE_URL)"; read answer; \
		[ "$$answer" = yes ] || { echo "reset-db: nothing changed"; exit 1; }; \
	fi
	@$(STACK) stop-for-reset
	@rm -f "$(OPS_RUN_DIR)/sample-team.installed" "$(OPS_RUN_DIR)/sample-library.installed"
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/schema_sync.py "$(OPS_DATABASE_URL)" --reset
	@$(MAKE) -s migrate

down: ## Stop what `make up` started, then compose (KEEP_DB=1 leaves compose running)
	@$(STACK) down
	@if [ "$(KEEP_DB)" != "1" ]; then $(MAKE) -s db-down; fi

restart: ## Restart the services `make up` started (SVC=agents|worker|tools|kb|files|platform|console for one), migrating each first
	@# Each service's chain is applied between stop and start, as make up does, so a restart of newer code never
	@# meets a table without its new columns. The console, the embed app, the API docs page, the runner and the fakes
	@# have no database; the worker uses agents-service's.
	@if [ -n "$(SVC)" ]; then \
		$(STACK) stop $(SVC) && \
		{ case "$(SVC)" in console|worker|embed|apidocs|runner|fakeai|fakebank) ;; *) $(MAKE) -s -C $(SVC_DIR_$(SVC)) migrate && $(STACK) note-migrations;; esac; } && \
		$(STACK) start $(SVC); \
	else \
		$(STACK) down && \
		for d in $(SVC_DIR_agents) $(SVC_DIR_tools) $(SVC_DIR_models) $(SVC_DIR_kb) $(SVC_DIR_platform) $(SVC_DIR_files) $(SVC_DIR_documents); do $(MAKE) -s -C $$d migrate || exit 1; done && \
		$(STACK) note-migrations && $(STACK) up; \
	fi
	@$(MAKE) -s plugins-check
	@$(STACK) health $(SVC)

health: ## Probe every service, OPA and PostgreSQL; shows port, state and who owns the listener
	@$(STACK) health

sample-team: ## Install the sample team (scripts/sample-team/sample-team.json) as the first admin; a second run finds it (NAME= another team, EXPECT_FOUND=1 fails on anything made)
	@MODEL=$(DEMO_MODEL) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_team.py install $(if $(NAME),--name "$(NAME)") $(if $(EXPECT_FOUND),--expect-found)

sample-library: ## Install the demo policy library (scripts/sample-team/library/library.json) in team Platform as the platform dev role; a second run finds it (EXPECT_FOUND=1 fails on anything made)
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_library.py $(if $(EXPECT_FOUND),--expect-found)

sample-teams: ## Install the first teams (scripts/sample-team/teams/*.json) with their people and knowledge, and each team's assistant; a second run finds them
	@for f in $(ROOT)/scripts/sample-team/teams/*.json; do \
		uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_team.py install --manifest "$$f" $(if $(EXPECT_FOUND),--expect-found) || exit 1; \
	done

logs: ## Follow one service's log: make logs SVC=agents|tools|runner|console (FOLLOW=0 to print and exit)
	@OPS_LOGS_FOLLOW=$(if $(FOLLOW),$(FOLLOW),1) $(STACK) logs $(SVC)

runner-wasm: ## Fetch the code runner's pinned Python build into .data/runner and check its SHA-256 (make up does it too)
	@$(MAKE) -s -C services/runner-service wasm

demo-walk: ## Walk the sample team: chat, guardrail, bank reads, a write a person approves, then an emailed levy notice to the second reply (PASS/FAIL each; re-runnable)
	@uv run --quiet --project $(ROOT) python $(ROOT)/scripts/sample_walk.py $(if $(NAME),--name "$(NAME)")

demo: sample-team demo-walk ## Install the sample team, then walk it

demo-salesforce: ## The Salesforce plugin demo on the stack: plugin installed, fake Salesforce (SF=real: the owner's org), model alias, account switch; RESET=1 starts the team admin's steps again
	@SF=$(SF) RESET=$(RESET) PLUGIN_REF=$(PLUGIN_REF) uv run --quiet --project $(ROOT) python $(ROOT)/scripts/demo_salesforce.py

demo-salesforce-templates: ## Story 3 of the Salesforce demo: the team admin adds the plugin's case helper and triage workflow as team copies through the Python SDK, and publishes them
	@# The SDK is its own project (sdk/python), as a developer installs it.
	@uv run --quiet --project $(ROOT)/sdk/python python $(ROOT)/scripts/demo_salesforce.py templates

demo-salesforce-walk: ## Walk the Salesforce demo's five stories in a browser on the stack's console; screenshots in .logs/demo-salesforce (SF=real stops at the owner's Allow)
	@SF=$(SF) node $(ROOT)/scripts/demo-salesforce/walk.mjs

demo-model: ## Point the agents' chat alias at a cheap real OpenAI model (MODEL=gpt-5-nano), or back at the fake (MODEL=fake)
	@MODEL=$(MODEL) uv run python scripts/demo_model.py

ports: ## Print the ports this stack uses
	@printf '  offset %s, compose project %s, state in %s\n' "$(OPS_PORT_OFFSET)" "$(OPS_COMPOSE_PROJECT)" "$(OPS_RUN_DIR)"
	@printf '  console %s (runtime %s), agents %s, tools %s, opa %s, postgres %s\n' $(OPS_CONSOLE_PORT) \
		$(OPS_CONSOLE_RUNTIME_PORT) $(OPS_AGENTS_PORT) $(OPS_TOOLS_PORT) $(OPS_OPA_PORT) $(OPS_PG_PORT)

##@ Call an API as a dev user

# `make api GET /v1/me AS=viewer`: the method and path are the words after `api`, so they become goals that do nothing.
# A query string goes in Q=, since make reads any word holding `=` as a variable.
ifneq ($(filter api,$(firstword $(MAKECMDGOALS))),)
API_WORDS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
# A path's colons (plugin:opsai.salesforce) are escaped, or make reads the path as a rule's target and prerequisites.
$(eval $(subst :,\:,$(API_WORDS)):;@:)
endif
# make's built-in AS (the assembler, `as`) means `AS ?=` never applies; only an unset or built-in AS takes the default.
ifneq ($(filter default undefined,$(origin AS)),)
AS := admin
endif
ENV ?= local

.PHONY: api sdk-call
api: ## make api GET /v1/me AS=<role>|james|<email> [Q='pageSize=5'] [BODY='{}'] [TEAM=] [SVC=] [ENV=staging]: signs in for real, prints the answer
	@[ -n "$(word 2,$(API_WORDS))" ] || { echo "make api: name the method and path, e.g. make api GET /v1/me AS=viewer" >&2; exit 2; }
	@uv run --quiet python scripts/api_as.py api $(word 1,$(API_WORDS)) '$(word 2,$(API_WORDS))$(if $(Q),?$(Q))' --as '$(AS)' --env $(ENV) \
		$(if $(BODY),--body '$(BODY)') $(if $(TEAM),--team $(TEAM)) $(if $(SVC),--service $(SVC))

sdk-call: ## make sdk-call CALL='ops.raw.platform.me_me()' AS=<role> [TEAM=] [ENV=staging]: one Python SDK call as that dev user
	@[ -n "$(CALL)" ] || { echo "make sdk-call: give the call, e.g. CALL='ops.raw.platform.me_me()' (double quotes inside it)" >&2; exit 2; }
	@uv run --quiet python scripts/api_as.py sdk '$(CALL)' --as '$(AS)' --env $(ENV) $(if $(TEAM),--team $(TEAM))
