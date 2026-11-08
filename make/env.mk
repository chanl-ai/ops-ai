# Ports, compose project and runtime env for the local stack. Included first by the root Makefile and by every service
# Makefile, so `make -C services/<x> <verb>` sees the same values as the root. Secrets come from the
# environment or from a gitignored .env at the root (contract: .env.example); a secrets-manager wrapper works the same
# way. Every name here is listed in docs/architecture/make.md.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)

# .env is optional. Plain KEY=value lines; values already in the caller's environment win (make does not override an
# environment variable with a file assignment unless told to), so a wrapper or an exported shell variable still rules.
-include $(ROOT)/.env
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' $(ROOT)/.env 2>/dev/null)
# Per-developer keys outside the image (devcontainer). Same KEY=value shape as .env.
-include $(ROOT)/.devcontainer/.env.local
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' $(ROOT)/.devcontainer/.env.local 2>/dev/null)

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
OPS_OPA_PORT ?= $(call port,8181)
OPS_PG_PORT ?= $(call port,5477)
# The test mail servers in compose: GreenMail takes mail in (SMTP) and serves it (IMAP); Mailpit catches sent mail.
# Their bases differ by multiples of 1000, so they move by a tenth of the offset; the whole offset would land on another's.
mail_port = $(shell echo $$(( $(1) + $(OPS_PORT_OFFSET) / 10 )))
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
  export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test_$(TEST_RUN))
  export OPS_DATABASE_URL ?= postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime
  export OPS_SMTP_HOST ?= 127.0.0.1
  export OPS_GREENMAIL_HOST ?= 127.0.0.1
  export OPS_MAILPIT_HOST ?= 127.0.0.1
endif
# Prefix for a test recipe: creates and migrates the test database, then runs the command against it.
TEST_DB = uv run --project $(ROOT) python $(ROOT)/scripts/test_db.py $(OPS_TEST_DATABASE_URL) && OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL)
export OPS_INFRA
# AUTH=platform (the default): agents and tools verify platform-service tokens and the console signs people in through
# it (James, Maya, Nadia from platform's dev seed); AUTH=dev runs dev auth and the mock sign-in. A stack already running
# keeps the mode it was started in, so `make restart SVC=x` without AUTH= never brings one service back in the other mode.
STARTED_AUTH := $(shell cat $(OPS_RUN_DIR)/console.auth $(OPS_RUN_DIR)/platform.auth 2>/dev/null | head -1)
AUTH ?= $(or $(STARTED_AUTH),platform)
export OPS_STACK_AUTH := $(if $(filter platform,$(AUTH)),platform,dev)
export OPS_CORS_ORIGINS ?= ["http://localhost:$(OPS_CONSOLE_PORT)","http://localhost:$(OPS_CONSOLE_RUNTIME_PORT)"]

COMPOSE := docker compose -p $(OPS_COMPOSE_PROJECT) -f $(ROOT)/deploy/compose/compose.yaml
STACK := $(ROOT)/scripts/stack.sh

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
