# Ports, compose project and runtime env for the local stack. Included first by the root Makefile and by every service
# Makefile, so `make -C services/<x> <verb>` sees the same values as the root. Secrets come from the
# environment or from a gitignored .env at the root (contract: .env.example); a secrets-manager wrapper works the same
# way. Every name here is listed in docs/architecture/make.md.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)

# .env is optional. Plain KEY=value lines. A key set in .env replaces the same key in the caller's environment (make lets a
# file assignment override an environment variable unless run with -e); keys the secrets command supplies (below) never do.
# OPS_EVIDENCE_DIR is the exception: it is where one run writes, so the caller's value wins.
OPS_EVIDENCE_DIR_CALLER := $(if $(filter environment,$(origin OPS_EVIDENCE_DIR)),$(OPS_EVIDENCE_DIR))
-include $(ROOT)/.env
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' $(ROOT)/.env 2>/dev/null)
# A .env copied from the host into a devcontainer or a worktree can name an evidence folder this machine cannot create
# (/Users/... inside a container). Such a value is dropped, so the use-case runner writes under .logs/usecases in the tree.
ifneq ($(OPS_EVIDENCE_DIR_CALLER),)
  OPS_EVIDENCE_DIR := $(OPS_EVIDENCE_DIR_CALLER)
else ifeq ($(origin OPS_EVIDENCE_DIR),file)
  ifeq ($(shell d='$(OPS_EVIDENCE_DIR)'; while [ ! -e "$$d" ]; do d=$$(dirname "$$d"); done; [ -d "$$d" ] && [ -w "$$d" ] && echo ok),)
    $(info OPS_EVIDENCE_DIR in .env ($(OPS_EVIDENCE_DIR)) cannot be written here; use cases write under .logs/usecases)
    undefine OPS_EVIDENCE_DIR
    unexport OPS_EVIDENCE_DIR
  endif
endif
# Per-developer keys outside the image (devcontainer). Same KEY=value shape as .env.
-include $(ROOT)/.devcontainer/.env.local
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' $(ROOT)/.devcontainer/.env.local 2>/dev/null)

# A secrets command is optional. When OPS_SECRETS_CMD is set (a secrets manager's export that prints KEY=value lines)
# and OPS_NO_SECRETS_CMD is unset or 0, scripts/secrets_cmd_env.py runs it once per top-level make: the keys are
# exported, so a sub-make sees them in its environment and OPS_SECRETS_LOADED skips the run. Precedence: the caller's
# environment, then the command, then .env, then .devcontainer/.env.local. The fragment is a mode-600 file under .run/
# that exists only while make reads it. `make help` skips it.
OPS_SECRETS_FILE := $(ROOT)/.run/secrets.mk
ifeq ($(strip $(OPS_SECRETS_CMD)),)
else ifneq ($(filter-out 0,$(strip $(OPS_NO_SECRETS_CMD)))$(OPS_SECRETS_LOADED),)
else ifneq ($(filter-out help,$(or $(MAKECMDGOALS),help)),)
$(shell rm -f '$(OPS_SECRETS_FILE)'; python3 '$(ROOT)/scripts/secrets_cmd_env.py' "$$OPS_SECRETS_CMD" '$(OPS_SECRETS_FILE)' 1>&2)
-include $(OPS_SECRETS_FILE)
ifneq ($(wildcard $(OPS_SECRETS_FILE)),)
export OPS_SECRETS_LOADED := 1
endif
$(shell rm -f '$(OPS_SECRETS_FILE)')
endif

# One stack per machine, on the fixed ports below, run from whichever checkout of this repository last ran `make up`
# (`make review` runs it from the review worktree). Its pids, logs and state (the first admin, the fake bank's
# certificate, the database heads) live in the main checkout, which every worktree of the repository shares, so moving
# the stack between checkouts restarts what runs from the other one instead of starting a second stack beside it.
STACK_HOME := $(or $(shell cd '$(ROOT)' && git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p'),$(ROOT))
# OPS_PORT_OFFSET adds a number to every default port, for a machine whose default ports are held by something this
# stack did not start. The compose project and the state folder follow it, so the offset stack never binds to or
# recreates the default stack's containers.
OPS_PORT_OFFSET ?= 0
ifeq ($(OPS_PORT_OFFSET),0)
  OPS_COMPOSE_PROJECT := ops-runtime
  OPS_LOG_DIR := $(STACK_HOME)/.logs
  OPS_RUN_DIR := $(STACK_HOME)/.run
  OPS_DATA_DIR := $(STACK_HOME)/.data
else
  OPS_COMPOSE_PROJECT := ops-runtime-$(OPS_PORT_OFFSET)
  OPS_LOG_DIR := $(STACK_HOME)/.logs/offset-$(OPS_PORT_OFFSET)
  OPS_RUN_DIR := $(STACK_HOME)/.run/offset-$(OPS_PORT_OFFSET)
  OPS_DATA_DIR := $(STACK_HOME)/.data/offset-$(OPS_PORT_OFFSET)
endif

# A test never stops, migrates or resets the stack: it runs on its own database (OPS_TEST_DATABASE_URL below).
STACK_GOALS := up down restart migrate reset-db db-down db-reset review sample-team sample-teams demo demo-walk demo-model
ifneq ($(filter $(STACK_GOALS),$(MAKECMDGOALS)),)
  ifdef PYTEST_CURRENT_TEST
    $(error refused: a test may not run $(filter $(STACK_GOALS),$(MAKECMDGOALS)) on the stack; tests run on their own database)
  endif
endif

# Every port is overridable from the environment or the make command line (`make up OPS_AGENTS_PORT=8750`); the
# defaults below plus OPS_PORT_OFFSET apply only when the caller set nothing.
comma := ,
port = $(shell echo $$(( $(1) + $(OPS_PORT_OFFSET) )))
OPS_CONSOLE_PORT ?= $(call port,3016)
# The embed app (apps/embed): the widget a bank page loads, and the console's preview frame.
OPS_EMBED_PORT ?= $(call port,3020)
OPS_CONSOLE_RUNTIME_PORT ?= $(call port,3017)
OPS_AGENTS_PORT ?= $(call port,8700)
OPS_TOOLS_PORT ?= $(call port,8720)
OPS_KB_PORT ?= $(call port,8740)
OPS_FILES_PORT ?= $(call port,8750)
OPS_DOCUMENTS_PORT ?= $(call port,8760)
# The code runner (services/runner-service) and the API docs site.
OPS_RUNNER_PORT ?= $(call port,8770)
OPS_API_DOCS_PORT ?= $(call port,8799)
OPS_MODELS_PORT ?= $(call port,8730)
OPS_FAKE_OPENAI_PORT ?= $(call port,8746)
# The fake bank (services/tools-service/scripts/fake_bank), reached as api.bank.test; each stack runs its own.
OPS_FAKE_BANK_PORT ?= $(call port,8745)
OPS_PLATFORM_PORT ?= $(call port,8710)
OPS_PLATFORM_INTERNAL_PORT ?= $(call port,8711)
# OPS_INFRA=shared: an offset stack reuses the default stack's postgres, OPA and mail containers, so their ports stay
# at the base values and the database is its own, ops_runtime_<offset>. The default stack (offset 0) owns the containers.
# The preview targets (make wt) run at offset 0 and start each stack at its own offset with OPS_INFRA passed on.
ifeq ($(OPS_INFRA),shared)
  ifneq ($(if $(MAKECMDGOALS),$(filter-out wt wt-list wt-stop,$(MAKECMDGOALS)),x),)
    # Only digits, no leading zero, not 0, one word: the offset names a database and lands in URLs.
    ifneq ($(strip $(subst 9,,$(subst 8,,$(subst 7,,$(subst 6,,$(subst 5,,$(subst 4,,$(subst 3,,$(subst 2,,$(subst 1,,$(subst 0,,$(OPS_PORT_OFFSET)))))))))))$(filter 0%,$(OPS_PORT_OFFSET))$(filter-out 1,$(words $(OPS_PORT_OFFSET)))),)
      $(error OPS_INFRA=shared needs OPS_PORT_OFFSET=N, digits only with no leading zero, got '$(OPS_PORT_OFFSET)')
    endif
    ifeq ($(OPS_PORT_OFFSET),0)
      $(error OPS_INFRA=shared is for an offset stack (OPS_PORT_OFFSET=N); the default stack starts the containers)
    endif
  endif
  infra_port = $(1)
else
  infra_port = $(call port,$(1))
endif
OPS_OPA_PORT ?= $(call infra_port,8181)
OPS_PG_PORT ?= $(call infra_port,5477)
# The test mail servers in compose: GreenMail takes mail in (SMTP) and serves it (IMAP); Mailpit catches sent mail.
# Their bases differ by multiples of 1000, so they move by a tenth of the offset; the whole offset would land on another's.
mail_port = $(if $(filter shared,$(OPS_INFRA)),$(1),$(shell echo $$(( $(1) + $(OPS_PORT_OFFSET) / 10 ))))
OPS_GREENMAIL_SMTP_PORT ?= $(call mail_port,3025)
OPS_GREENMAIL_IMAP_PORT ?= $(call mail_port,3143)
OPS_MAILPIT_SMTP_PORT ?= $(call mail_port,1025)
OPS_MAILPIT_HTTP_PORT ?= $(call mail_port,8025)
# A .env that names the default stack's models-service or fake model would send an offset stack's model calls there.
ifneq ($(OPS_PORT_OFFSET),0)
  ifneq ($(filter file environment,$(origin OPS_MODELS_URL)),)
    OPS_MODELS_URL := http://127.0.0.1:$(OPS_MODELS_PORT)
  endif
  ifneq ($(filter file environment,$(origin OPS_MODELS_FAKE_OPENAI_URL)),)
    OPS_MODELS_FAKE_OPENAI_URL := http://127.0.0.1:$(OPS_FAKE_OPENAI_PORT)/v1
  endif
endif

export OPS_PORT_OFFSET OPS_COMPOSE_PROJECT OPS_CONSOLE_PORT OPS_EMBED_PORT OPS_CONSOLE_RUNTIME_PORT OPS_AGENTS_PORT OPS_TOOLS_PORT OPS_KB_PORT OPS_FILES_PORT \
  OPS_DOCUMENTS_PORT OPS_RUNNER_PORT OPS_API_DOCS_PORT OPS_MODELS_PORT OPS_FAKE_OPENAI_PORT OPS_FAKE_BANK_PORT \
  OPS_PLATFORM_PORT OPS_PLATFORM_INTERNAL_PORT \
  OPS_OPA_PORT OPS_PG_PORT OPS_GREENMAIL_SMTP_PORT OPS_GREENMAIL_IMAP_PORT OPS_MAILPIT_SMTP_PORT OPS_MAILPIT_HTTP_PORT \
  OPS_LOG_DIR OPS_RUN_DIR OPS_DATA_DIR STACK_HOME

# The services read OPS_* (packages/ops_service_kit settings). These derive from the ports above so an overridden or
# offset port reaches the service; with the defaults they equal the settings defaults. A value already in the caller's
# environment wins.
export OPS_PORT ?= $(OPS_AGENTS_PORT)
export OPS_GATEWAY_PORT ?= $(OPS_TOOLS_PORT)
# Where the other services find platform-service's key set and introspection; the internal port binds to localhost.
export OPS_PLATFORM_URL ?= http://127.0.0.1:$(OPS_PLATFORM_PORT)
export OPS_PLATFORM_INTERNAL_URL ?= http://127.0.0.1:$(OPS_PLATFORM_INTERNAL_PORT)
# OPS_INFRA=external: postgres, opa, greenmail and mailpit already run as side containers (the
# devcontainer compose project). Skip db-up/db-down and use those service names. Every other default stays.
# Tests run on their own database, never the live ops_runtime: the live service's timer poller claims timers on any
# database it shares with the tests. A caller's explicit OPS_DATABASE_URL still wins; read before the default below.
# Exported, so a sub-make keeps the top-level choice instead of reading the exported live URL as explicit.
# Named for this make run (its pid and a random part): two runs at once, two sessions or QA beside a hand-back, never
# share a test database, where one run's per-test cleanup waited on the other's locks and the run hung. test_db.py drops
# the databases of runs that are over before it makes this one (scripts/scratch_db_sweep.py), as `make db-sweep` does.
TEST_RUN := r$(shell echo $$PPID)_$(shell od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
ifeq ($(OPS_INFRA),external)
  export OPS_OPA_URL ?= http://opa:8181
  export OPS_DATABASE_URL ?= postgresql+asyncpg://ops:ops@postgres:5432/ops_runtime
  export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@postgres:5432/ops_test_$(TEST_RUN))
  export OPS_SMTP_HOST ?= mailpit
  export OPS_GREENMAIL_HOST ?= greenmail
  export OPS_MAILPIT_HOST ?= mailpit
else
  export OPS_OPA_URL ?= http://127.0.0.1:$(OPS_OPA_PORT)
  ifeq ($(OPS_INFRA),shared)
    # The database is this stack's by its offset, whatever OPS_DATABASE_URL the environment holds (the default stack's
    # make exports its own), so a reset or a run never lands on the default stack's ops_runtime.
    override OPS_DATABASE_URL := postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime_$(OPS_PORT_OFFSET)
    export OPS_DATABASE_URL
    export OPS_TEST_DATABASE_URL ?= postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test_$(TEST_RUN)
  else
    export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test_$(TEST_RUN))
    export OPS_DATABASE_URL ?= postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime
  endif
  export OPS_SMTP_HOST ?= 127.0.0.1
  export OPS_GREENMAIL_HOST ?= 127.0.0.1
  export OPS_MAILPIT_HOST ?= 127.0.0.1
endif
# Prefix for a test recipe: creates and migrates the test database, then runs the command against it.
# PAR=<n> runs the suite on n pytest-xdist workers, each on its own copy of the test database (scripts/test_db.py
# --workers), a whole test file to one worker. Only for the suites below, each of which passed three runs in a row in
# parallel; any other refuses, since a suite that shares state between files fails at random instead.
PAR_SUITES := agents-service tools-service platform-service documents-service files-service models-service
PAR_RUN = $(if $(PAR),$(if $(filter $(notdir $(CURDIR)),$(PAR_SUITES)),--workers $(PAR),$(error PAR=: $(notdir $(CURDIR)) has not been proven safe in parallel; run it without PAR)))
# The pytest arguments, which a suite's test recipe puts after `pytest` (not PYTEST_ADDOPTS: a test that starts pytest
# itself would inherit them).
PYTEST_PAR = $(if $(PAR),-n $(PAR) --dist loadfile)
TEST_DB = uv run --project $(ROOT) python $(ROOT)/scripts/test_db.py $(OPS_TEST_DATABASE_URL) --service $(notdir $(CURDIR)) $(PAR_RUN) && OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL)
export OPS_INFRA
# AUTH=platform (the default): agents and tools verify platform-service tokens and the console signs people in through
# it (James, Maya, Nadia from platform's dev seed); AUTH=dev runs dev auth and the mock sign-in. A stack already running
# keeps the mode it was started in, so `make restart SVC=x` without AUTH= never brings one service back in the other mode.
STARTED_AUTH := $(shell cat $(OPS_RUN_DIR)/console.auth $(OPS_RUN_DIR)/platform.auth 2>/dev/null | head -1)
AUTH ?= $(or $(STARTED_AUTH),platform)
export OPS_STACK_AUTH := $(if $(filter platform,$(AUTH)),platform,dev)
export OPS_CORS_ORIGINS ?= ["http://localhost:$(OPS_CONSOLE_PORT)","http://localhost:$(OPS_CONSOLE_RUNTIME_PORT)"]

COMPOSE := docker compose -p $(OPS_COMPOSE_PROJECT) -f $(ROOT)/deploy/compose/compose.yaml
# The containers postgres runs in: this stack's compose project, or under OPS_INFRA=shared the default stack's. DB_NAME
# is the stack's own database in it.
DB_COMPOSE := $(if $(filter shared,$(OPS_INFRA)),docker compose -p ops-runtime -f $(ROOT)/deploy/compose/compose.yaml,$(COMPOSE))
DB_NAME := ops_runtime$(if $(filter shared,$(OPS_INFRA)),_$(OPS_PORT_OFFSET))
STACK := $(ROOT)/scripts/stack.sh
# A service's `make run` in the foreground, on the command `make up` starts it with (`stack.sh cmd`): the other
# services' addresses and the sign-in mode, without which the service refuses to start. `$(call STACK_RUN,kb)`.
STACK_RUN = cd $(ROOT) && $$($(STACK) cmd $(1))

# `make help` in any Makefile: targets with a `## ` comment, grouped by `##@` headings.
define HELP_AWK
BEGIN { FS = ":.*## " } /^##@/ { printf "\n%s\n", substr($$0, 5) } /^[a-z0-9-]+:.*## / { printf "  %-20s %s\n", $$1, $$2 }
endef
export HELP_AWK

# A verify run keeps going after a failing check (-k) and still fails at the end: the root's verify runs its
# console, docs and python prerequisites, and a service's verify its lint, typecheck, test, standards and openapi
# checks, each to the end, so a red never hides the reds after it. env.mk is the one file both include.
ifneq ($(filter verify python-verify,$(MAKECMDGOALS)),)
MAKEFLAGS += -k
endif
