# Ports, compose project and runtime env for the local stack. Included first by the root Makefile and by every service
# Makefile, so `make -C services/<x> <verb> ISOLATED=1` sees the same values as the root. Secrets come from the
# environment or from a gitignored .env at the root (contract: .env.example); a secrets-manager wrapper works the same
# way. Every name here is listed in docs/architecture/make.md.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)

# .env is optional. Plain KEY=value lines; values already in the caller's environment win (make does not override an
# environment variable with a file assignment unless told to), so a wrapper or an exported shell variable still rules.
-include $(ROOT)/.env
export $(shell sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' $(ROOT)/.env 2>/dev/null)

# ISOLATED=1 runs a second stack beside the first: every port +1000, its own compose project and data volume, its own
# logs and pids, so two checkouts or two sessions do not fight over :8700 or one database.
ifeq ($(ISOLATED),1)
  OPS_PORT_OFFSET := 1000
  OPS_STACK := isolated
  OPS_COMPOSE_PROJECT := ops-runtime-isolated
else
  OPS_PORT_OFFSET := 0
  OPS_STACK := shared
  OPS_COMPOSE_PROJECT := ops-runtime
endif

# Every port is overridable from the environment or the make command line (`make up OPS_AGENTS_PORT=8750`); the
# defaults below plus the ISOLATED offset apply only when the caller set nothing.
port = $(shell echo $$(( $(1) + $(OPS_PORT_OFFSET) )))
OPS_CONSOLE_PORT ?= $(call port,3016)
OPS_CONSOLE_RUNTIME_PORT ?= $(call port,3017)
OPS_AGENTS_PORT ?= $(call port,8700)
OPS_TOOLS_PORT ?= $(call port,8720)
OPS_PLATFORM_PORT ?= $(call port,8710)
OPS_PLATFORM_INTERNAL_PORT ?= $(call port,8711)
OPS_OPA_PORT ?= $(call port,8181)
OPS_PG_PORT ?= $(call port,5477)
OPS_LOG_DIR := $(ROOT)/.logs$(if $(filter 1,$(ISOLATED)),/isolated)
OPS_RUN_DIR := $(ROOT)/.run$(if $(filter 1,$(ISOLATED)),/isolated)

export OPS_STACK OPS_COMPOSE_PROJECT OPS_CONSOLE_PORT OPS_CONSOLE_RUNTIME_PORT OPS_AGENTS_PORT OPS_TOOLS_PORT \
  OPS_PLATFORM_PORT OPS_PLATFORM_INTERNAL_PORT \
  OPS_OPA_PORT OPS_PG_PORT OPS_LOG_DIR OPS_RUN_DIR

# The services read OPS_* (packages/ops_service_kit settings). These derive from the ports above so an overridden or
# offset port reaches the service; with the defaults they equal the settings defaults. A value already in the caller's
# environment wins.
export OPS_PORT ?= $(OPS_AGENTS_PORT)
export OPS_GATEWAY_PORT ?= $(OPS_TOOLS_PORT)
# Where the other services find platform-service's key set and introspection; the internal port binds to localhost.
export OPS_PLATFORM_URL ?= http://127.0.0.1:$(OPS_PLATFORM_PORT)
export OPS_OPA_URL ?= http://127.0.0.1:$(OPS_OPA_PORT)
# Tests run on their own database, never the live ops_runtime: the live service's timer poller claims timers on any
# database it shares with the tests. A caller's explicit OPS_DATABASE_URL still wins; read before the default below.
# Exported, so a sub-make keeps the top-level choice instead of reading the exported live URL as explicit.
export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test$(if $(filter 1,$(ISOLATED)),_isolated))
# Prefix for a test recipe: creates and migrates the test database, then runs the command against it.
TEST_DB = uv run --project $(ROOT) python $(ROOT)/scripts/test_db.py $(OPS_TEST_DATABASE_URL) && OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL)
export OPS_DATABASE_URL ?= postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime
# AUTH=platform: agents and tools verify platform-service tokens and the console signs people in through it (James,
# Maya, Nadia from platform's dev seed) instead of the mock; unset, the stack runs dev auth and the mock sign-in.
export OPS_STACK_AUTH := $(if $(filter platform,$(AUTH)),platform,dev)
export OPS_CORS_ORIGINS ?= ["http://localhost:$(OPS_CONSOLE_PORT)","http://localhost:$(OPS_CONSOLE_RUNTIME_PORT)"]

COMPOSE := docker compose -p $(OPS_COMPOSE_PROJECT) -f $(ROOT)/deploy/compose/compose.yaml
STACK := $(ROOT)/scripts/stack.sh

# `make help` in any Makefile: targets with a `## ` comment, grouped by `##@` headings.
define HELP_AWK
BEGIN { FS = ":.*## " } /^##@/ { printf "\n%s\n", substr($$0, 5) } /^[a-z0-9-]+:.*## / { printf "  %-20s %s\n", $$1, $$2 }
endef
export HELP_AWK
