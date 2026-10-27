# Ports, compose project and runtime env for the local stack. Included first by the root Makefile and by every service
# Makefile, so `make -C services/<x> <verb> ISOLATED=1` sees the same values as the root. Secrets come from the
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
comma := ,
port = $(shell echo $$(( $(1) + $(OPS_PORT_OFFSET) )))
OPS_CONSOLE_PORT ?= $(call port,3016)
# The embed app (apps/embed): the widget a bank page loads, and the console's preview frame (c-232).
OPS_EMBED_PORT ?= $(call port,3020)
OPS_CONSOLE_RUNTIME_PORT ?= $(call port,3017)
OPS_AGENTS_PORT ?= $(call port,8700)
OPS_TOOLS_PORT ?= $(call port,8720)
OPS_KB_PORT ?= $(call port,8740)
OPS_FILES_PORT ?= $(call port,8750)
OPS_DOCUMENTS_PORT ?= $(call port,8760)
# The code runner (services/runner-service, c-531) and the API docs site. Without the offset an isolated stack's runner
# took the shared stack's :8770, and the shared `make up` found that port healthy and called back the other stack.
OPS_RUNNER_PORT ?= $(call port,8770)
OPS_API_DOCS_PORT ?= $(call port,8799)
OPS_MODELS_PORT ?= $(call port,8730)
OPS_FAKE_OPENAI_PORT ?= $(call port,8746)
OPS_PLATFORM_PORT ?= $(call port,8710)
OPS_PLATFORM_INTERNAL_PORT ?= $(call port,8711)
OPS_OPA_PORT ?= $(call port,8181)
OPS_PG_PORT ?= $(call port,5477)
# The test mail servers in compose (c-192): GreenMail takes mail in (SMTP) and serves it (IMAP); Mailpit catches sent mail.
OPS_GREENMAIL_SMTP_PORT ?= $(call port,3025)
OPS_GREENMAIL_IMAP_PORT ?= $(call port,3143)
OPS_MAILPIT_SMTP_PORT ?= $(call port,1025)
OPS_MAILPIT_HTTP_PORT ?= $(call port,8025)
# A make run started inside another (a use case's runner, a recipe) inherits the outer stack's exported addresses, and
# `?=` keeps them, so an ISOLATED=1 run from inside a shared one would act on the shared stack (c-099, tick 14). With
# ISOLATED=1 every address that came from the environment is recomputed; one given on the make command line still wins.
# GNU Make 3.81 (macOS) has no undefine, hence the reassignment.
reset_inherited = $(if $(filter 1,$(ISOLATED)),$(foreach v,$(1),$(if $(filter environment,$(origin $(v))),$(eval $(v) := $(2)))))
$(call reset_inherited,OPS_CONSOLE_PORT,$(call port,3016))
$(call reset_inherited,OPS_EMBED_PORT,$(call port,3020))
$(call reset_inherited,OPS_CONSOLE_RUNTIME_PORT,$(call port,3017))
$(call reset_inherited,OPS_AGENTS_PORT,$(call port,8700))
$(call reset_inherited,OPS_TOOLS_PORT,$(call port,8720))
$(call reset_inherited,OPS_KB_PORT,$(call port,8740))
$(call reset_inherited,OPS_FILES_PORT,$(call port,8750))
$(call reset_inherited,OPS_DOCUMENTS_PORT,$(call port,8760))
$(call reset_inherited,OPS_RUNNER_PORT,$(call port,8770))
$(call reset_inherited,OPS_API_DOCS_PORT,$(call port,8799))
$(call reset_inherited,OPS_MODELS_PORT,$(call port,8730))
$(call reset_inherited,OPS_FAKE_OPENAI_PORT,$(call port,8746))
$(call reset_inherited,OPS_PLATFORM_PORT,$(call port,8710))
$(call reset_inherited,OPS_PLATFORM_INTERNAL_PORT,$(call port,8711))
$(call reset_inherited,OPS_OPA_PORT,$(call port,8181))
$(call reset_inherited,OPS_PG_PORT,$(call port,5477))
$(call reset_inherited,OPS_GREENMAIL_SMTP_PORT,$(call port,3025))
$(call reset_inherited,OPS_GREENMAIL_IMAP_PORT,$(call port,3143))
$(call reset_inherited,OPS_MAILPIT_SMTP_PORT,$(call port,1025))
$(call reset_inherited,OPS_MAILPIT_HTTP_PORT,$(call port,8025))
OPS_LOG_DIR := $(ROOT)/.logs$(if $(filter 1,$(ISOLATED)),/isolated)
OPS_RUN_DIR := $(ROOT)/.run$(if $(filter 1,$(ISOLATED)),/isolated)

export OPS_STACK OPS_COMPOSE_PROJECT OPS_CONSOLE_PORT OPS_EMBED_PORT OPS_CONSOLE_RUNTIME_PORT OPS_AGENTS_PORT OPS_TOOLS_PORT OPS_KB_PORT OPS_FILES_PORT \
  OPS_DOCUMENTS_PORT OPS_RUNNER_PORT OPS_API_DOCS_PORT OPS_MODELS_PORT OPS_FAKE_OPENAI_PORT \
  OPS_PLATFORM_PORT OPS_PLATFORM_INTERNAL_PORT \
  OPS_OPA_PORT OPS_PG_PORT OPS_GREENMAIL_SMTP_PORT OPS_GREENMAIL_IMAP_PORT OPS_MAILPIT_SMTP_PORT OPS_MAILPIT_HTTP_PORT \
  OPS_LOG_DIR OPS_RUN_DIR

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
  export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@postgres:5432/ops_test$(if $(filter 1,$(ISOLATED)),_isolated)_$(TEST_RUN))
  export OPS_SMTP_HOST ?= mailpit
  export OPS_GREENMAIL_HOST ?= greenmail
  export OPS_MAILPIT_HOST ?= mailpit
else
  export OPS_OPA_URL ?= http://127.0.0.1:$(OPS_OPA_PORT)
  export OPS_TEST_DATABASE_URL ?= $(if $(filter environment command line,$(origin OPS_DATABASE_URL)),$(OPS_DATABASE_URL),postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test$(if $(filter 1,$(ISOLATED)),_isolated)_$(TEST_RUN))
  export OPS_DATABASE_URL ?= postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime
  export OPS_SMTP_HOST ?= 127.0.0.1
  export OPS_GREENMAIL_HOST ?= 127.0.0.1
  export OPS_MAILPIT_HOST ?= 127.0.0.1
endif
# Prefix for a test recipe: creates and migrates the test database, then runs the command against it.
TEST_DB = uv run --project $(ROOT) python $(ROOT)/scripts/test_db.py $(OPS_TEST_DATABASE_URL) && OPS_DATABASE_URL=$(OPS_TEST_DATABASE_URL)
export OPS_INFRA
$(call reset_inherited,OPS_PORT,$(OPS_AGENTS_PORT))
$(call reset_inherited,OPS_GATEWAY_PORT,$(OPS_TOOLS_PORT))
$(call reset_inherited,OPS_PLATFORM_URL,http://127.0.0.1:$(OPS_PLATFORM_PORT))
$(call reset_inherited,OPS_OPA_URL,http://127.0.0.1:$(OPS_OPA_PORT))
$(call reset_inherited,OPS_DATABASE_URL,postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_runtime)
$(call reset_inherited,OPS_TEST_DATABASE_URL,postgresql+asyncpg://ops:ops@localhost:$(OPS_PG_PORT)/ops_test_isolated_$(TEST_RUN))
# The shared stack's live database, which only a shared-stack reset may drop (see reset-db in dev.mk).
SHARED_DATABASE := localhost:5477/ops_runtime
# AUTH=platform: agents and tools verify platform-service tokens and the console signs people in through it (James,
# Maya, Nadia from platform's dev seed) instead of the mock; AUTH=dev runs dev auth and the mock sign-in. The shared
# stack defaults to platform, the one the demos run on; an isolated stack defaults to dev.
AUTH ?= $(if $(filter shared,$(OPS_STACK)),platform,dev)
export OPS_STACK_AUTH := $(if $(filter platform,$(AUTH)),platform,dev)
export OPS_CORS_ORIGINS ?= ["http://localhost:$(OPS_CONSOLE_PORT)","http://localhost:$(OPS_CONSOLE_RUNTIME_PORT)"]
$(call reset_inherited,OPS_CORS_ORIGINS,["http://localhost:$(OPS_CONSOLE_PORT)"$(comma)"http://localhost:$(OPS_CONSOLE_RUNTIME_PORT)"])

COMPOSE := docker compose -p $(OPS_COMPOSE_PROJECT) -f $(ROOT)/deploy/compose/compose.yaml
STACK := $(ROOT)/scripts/stack.sh

# `make help` in any Makefile: targets with a `## ` comment, grouped by `##@` headings.
define HELP_AWK
BEGIN { FS = ":.*## " } /^##@/ { printf "\n%s\n", substr($$0, 5) } /^[a-z0-9-]+:.*## / { printf "  %-20s %s\n", $$1, $$2 }
endef
export HELP_AWK

# A verify run keeps going after a failing check (-k) and still fails at the end (c-367): the root's verify runs its
# console, docs and python prerequisites, and a service's verify its lint, typecheck, test, standards and openapi
# checks, each to the end, so a red never hides the reds after it. env.mk is the one file both include.
ifneq ($(filter verify python-verify,$(MAKECMDGOALS)),)
MAKEFLAGS += -k
endif
