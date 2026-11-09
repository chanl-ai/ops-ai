# Make

Status: current, 2026-11-06. Describes how `make` is organised in this repo and the commands for daily work. Update it in the
same change as any Makefile.

## Layering

| Layer | File | Owns |
|---|---|---|
| Orchestration | `Makefile` | `help`, `install`, `verify`, `clean`; includes the fragments below. No service logic |
| Concerns | `make/*.mk` | One fragment per concern; each target is defined in exactly one fragment |
| Services | `services/<x>/Makefile`, `apps/console/Makefile` | The same verb set everywhere; root targets reach them with `$(MAKE) -C` |
| Process manager | `scripts/stack.sh` | Starts, stops, probes and tails the background processes for `make up` |

Every Makefile, root or service, includes `make/env.mk` first (service Makefiles through `make/service-common.mk` or
`make/service-stub.mk`), so a port or `OPS_PORT_OFFSET` set on the command line means the same wherever it is typed.

## One stack per machine

One stack runs on a machine, on the fixed ports below, from whichever checkout of the repository last ran `make up`.
Its pids, logs and state (`.run/`, `.logs/`, `.data/`, the installed `plugins/`) live in the main checkout, which
every worktree of the repository shares, so a stack started from another worktree replaces it instead of running
beside it.

| Command | What it does |
|---|---|
| `make up` | Runs the stack from this checkout: migrates, then restarts each service whose process runs another checkout's code or another commit's (`.run/<svc>.rev` records both at start), and starts what is down |
| `make review BRANCH=<name>` | Fetches the branch, checks it out detached in the review worktree beside the main checkout (`<main checkout>-review`, made on first use, its `.env` copied from the main checkout), installs, then runs `make up` there. Your own checkout and branch stay as they are; it refuses when the review worktree has uncommitted changes. `make up` in your checkout moves the stack back |
| `make test PKG=<folder>` | One member's tests (`T=` some files), on a throwaway database of its own on the stack's PostgreSQL; with no `PKG`, the suites of what changed since `origin/main` (`scripts/verify-changed.sh`) |

A branch made before this change has the old make files, which refuse to run a stack from a worktree: merge `main`
into it before reviewing it.

## Fragments

| Fragment | Targets | Owns |
|---|---|---|
| `make/env.mk` | none | Ports (overridable defaults), `OPS_PORT_OFFSET`, compose project, the stack's state folders in the main checkout, the `OPS_*` the services read derived from the ports, the help formatter |
| `make/dev.mk` | `up`, `down`, `restart`, `health`, `logs`, `ports`, `api`, `sdk-call` | The local stack through `scripts/stack.sh`; one route or SDK call as a seeded person (`scripts/api_as.py`) |
| `make/cli.mk` | `<area>-<verb>` (`chat`, `kb-*`, `apps-*`, `tools-*`, `runs-*`, `tasks-*`, `cases-*`, `files-*`, `documents-*`, `people-*`, `models-*`, `memories-*`), `test-data-clean` | The `ops` command (`sdk/python`) as a seeded person (`AS=`); the list: `make/CLAUDE.md` |
| `make/db.mk` | `db-up`, `db-down`, `db-shell`, `db-reset`, `migrate`, `migration` | Compose (PostgreSQL, OPA) and Alembic |
| `make/db-scripts.mk` | `db-ddl`, `db-upgrade-sql`, `db-drift`, `db-release`, `db-scripts-proof` | The schema as scripts a DBA applies (`deploy/database/schema.py`, `docs/deploy/database.md`) |
| `make/services.mk` | `<verb>-<svc>`, generated | `SERVICES`, each service's folder, `SERVICE_VERBS`; one rule template expanded per pair |
| `make/console.mk` | `console-install`, `dev`, `dev-runtime`, `console-verify` | The console in the foreground |
| `make/python.mk` | `python-install`, `python-verify`, `test` | The uv workspace: ruff and pyright on `packages/`, then each service's verify with model keys unset |
| `make/docs.mk` | `docs-verify` | `scripts/check-docs.mjs` |
| `make/sdk.mk` | `sdk`, `sdk-verify`, `sdk-check` | The SDKs in `sdk/`: regenerate, the drift check and both test suites (in `verify`), and the install smoke plus the examples on `make up` |
| `make/usecase.mk` | `usecase-test`, `usecase-list`, `usecase-show`, `usecase-coverage`, `usecase-new`, `usecase-runner-test` | Calls `scripts/usecase.mjs` (`packages/usecase-runner`); use-case ports and database `OPS_USECASE_*`. Registry and rules: `docs/usecases/README.md` |
| `make/git.mk` | `commit`, `commit-hunks`, `review` | Committing named files through the hooks, and the review worktree |
| `make/plugins.mk` | `plugins-sync`, `plugins-bump` | Putting the plugins `deploy/plugins.json` pins into `OPS_PLUGINS_DIR`, and moving the pins |
| `make/experiments.mk` | `experiment` | Runs `services/agents-service/experiments/e<n>_*.py` on the scripted model |
| `make/service-common.mk` | `help`, `stop`, `logs`, `health` | Included by running services' Makefiles: the verbs that act on the `make up` process |
| `make/service-stub.mk` | the whole verb set | Included by planned services' Makefiles: every verb answers "not started" unless the Makefile defines it (`OWN_VERBS`) |

## Service verb set

Every service Makefile answers these. `make -C services/<x> help` lists them.

| Verb | agents-service | tools-service | platform-service | models-service, kb-service | console | files-service |
|---|---|---|---|---|---|---|
| `install` | `uv sync --frozen` | `uv sync --frozen` | `uv sync --frozen` | `uv sync --frozen` | `pnpm install` at the root | own `uv sync` |
| `run` | foreground on 8700 | foreground on 8720 | foreground on 8710 and 8711 | foreground on 8730 and 8740 | `next dev` on 3016 | foreground on 8750 |
| `stop` | stops the `make up` process | same | same | not started | same | stops the `make up` process |
| `test` | pytest (needs `db-up`) | gateway tests in agents-service | pytest (needs `db-up`) | pytest (needs `db-up`) | none yet, says so | pytest (needs `db-up`) |
| `lint` | ruff format and check | ruff | ruff | ruff | standards check | ruff |
| `typecheck` | strict pyright | strict pyright | strict pyright | strict pyright | `tsc --noEmit` | pyright |
| `verify` | lint, typecheck, db-up, test, standards | lint, typecheck, test | lint, typecheck, test, OpenAPI check | lint, typecheck, test, OpenAPI check | tsc and standards | lint, typecheck, test, OpenAPI check |
| `migrate` | Alembic upgrade head | runs agents-service's | own chain (`alembic_version_platform`) | own chains (`alembic_version_models`, `alembic_version_kb`) | none | own chain (`alembic_version_files`) |
| `logs` | tails `.logs/agents.log` | `.logs/tools.log` | `.logs/platform.log` | not started (kb: `make logs SVC=kb` from the root) | `.logs/console.log` | `.logs/files.log` |
| `health` | probes `/health` | probes `/health` | probes `/health` | not started (kb: `make health` from the root) | probes `/health` |
| `clean` | caches | caches | caches | caches | `.next` build directories | caches |

`make up` starts every service, the workflow worker, the console and embed app, models-service and the dev fakes
(the fake model and the fake bank). `services/hitl-service` holds only a stub `Makefile`
and `README.md`; the service was removed on 2026-10-16, and Reviews move into the `ops_hitl` package.

A service is stale when its process runs from another checkout, when its code differs between the commit it started on and HEAD (its own folder, `packages/` and `uv.lock` for a Python service; `package.json`, the Next config and `pnpm-lock.yaml` for the console and embed app, whose sources `next dev` reloads), or, for a Python service, when it started before the last migration landed: `make migrate` records each chain's revision in `.run/db-heads` and touches `.run/migrated-at` when one moved. `make up` stops stale processes before and after migrating, then starts them.

Feedback button: run the ui-feedback collector (`node ~/.claude/skills/ui-feedback/collector.mjs`) before `make up` or the docs `pnpm dev`; development only, a production build never shows it.

## Naming rules

| Rule | Example |
|---|---|
| Verb first, then the noun | `db-up`, `run-agents`, `usecase-test` |
| Per-service variants take `SVC=` | `make logs SVC=agents`, `make restart SVC=tools` |
| Generated per-service targets are `<verb>-<svc>` | `test-agents`, `verify-tools`, `run-console` |
| `OPS_PORT_OFFSET=<n>` adds n to every default port, for a machine whose defaults another program holds | `make up OPS_PORT_OFFSET=30000`; its own compose project (`ops-runtime-<n>`) and state folders (`.run/offset-<n>`, `.logs/offset-<n>`, `.data/offset-<n>`) |
| `OPS_INFRA=external` uses side containers | `make up OPS_INFRA=external` skips `db-up`/`db-down` and points the database, OPA and mail hosts at compose service names; the fake bank is the compose sidecar `api.bank.test`, not a process in the workspace |
| Any one port moved, the services and console follow | `make up OPS_AGENTS_PORT=8750` (or set it in the environment); every `OPS_*_PORT` in `make/env.mk` is a default, not a constant |
| A target lives in one fragment only; others call it | `migrate` is in `db.mk`; `up` calls it after the schema step |
| Every public target has a `## ` comment; `##@` starts a help group | `make help` reads them |

## Environment

Secrets come from the environment or from a gitignored `.env` at the root (copy `.env.example`); make loads it and exports every line to the services, the console and the use-case runner. A secrets-manager wrapper (`<wrapper> -- make up`) works the same way and wins over the file.
Services read `OPS_*` (`packages/ops_service_kit/src/ops_service_kit/settings.py`); make sets the `OPS_*`
values below. The prefix was `OPS_RUNTIME_` before the service rename: rename any `OPS_RUNTIME_*` variable in your
shell or secrets manager to `OPS_*`.

| Name | Default | Set by | Read by |
|---|---|---|---|
| `OPS_PORT_OFFSET` | 0 | you | `make/env.mk`: added to every default port; names the compose project and state folders when not 0 |
| `STACK_HOME` | the main checkout (first entry of `git worktree list`) | `env.mk` | `stack.sh`, `demo_salesforce.py`: where the stack's state lives |
| `OPS_INFRA` | unset (`external` in a devcontainer) | you or `.devcontainer/devcontainer.json` | `env.mk`, `db.mk`, `stack.sh`: skip `db-up`/`db-down`; set `OPS_DATABASE_URL`, `OPS_TEST_DATABASE_URL`, `OPS_OPA_URL`, `OPS_SMTP_HOST`, `OPS_GREENMAIL_HOST`, `OPS_MAILPIT_HOST` to the compose service names; skip the in-process fake bank (the compose sidecar is `api.bank.test`) |
| `OPS_COMPOSE_PROJECT` | `ops-runtime` (`ops-runtime-<offset>`) | `env.mk` | `docker compose -p` |
| `OPS_CONSOLE_PORT`, `OPS_CONSOLE_RUNTIME_PORT` | 3016, 3017 | `env.mk` | `stack.sh`, console Makefile |
| `OPS_AGENTS_PORT`, `OPS_TOOLS_PORT` | 8700, 8720 | `env.mk` | `stack.sh` |
| `OPS_FILES_PORT` | 8750 | `env.mk` | `stack.sh` (files) |
| `OPS_OPA_PORT`, `OPS_PG_PORT` | 8181, 5477 | `env.mk` | `stack.sh`, `deploy/compose/compose.yaml` |
| `OPS_LOG_DIR`, `OPS_RUN_DIR`, `OPS_DATA_DIR` | `.logs`, `.run`, `.data` in the main checkout (`/offset-<n>` appended) | `env.mk` | `stack.sh`, which also points the services' `OPS_FILES_DIR`, `OPS_KB_FILES_DIR`, `OPS_RUNNER_CACHE_DIR`, `OPS_MAIL_FAKE_OUT_DIR` and `OPS_PLUGINS_DIR` (the main checkout's `plugins/`) there, unless `.env` sets them |
| `OPS_READY_TIMEOUT` | 90 | you | `stack.sh up` wait |
| `OPS_CONSOLE_DIST_DIR` | `.next` | the use-case runner, for its own build | `apps/console/next.config.ts` |
| `OPS_GATEWAY_URL` | tools-service on `OPS_TOOLS_PORT` | `stack.sh` (agents and worker) | agents: tools come from and run through tools-service; agents are seeded from `services/agents-service/seed/` |
| `OPS_PORT`, `OPS_GATEWAY_PORT` | 8700, 8720 | settings default; `env.mk` from the ports | agents, tools |
| `OPS_DATABASE_URL` | `postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime` | settings default; `env.mk` from `OPS_PG_PORT` | agents, tools, Alembic |
| `OPS_TEST_DATABASE_URL` | `…/ops_test_r<make pid>_<hex>`, one per make run so two runs never share one; `test_db.py` drops finished runs' databases first; a caller's explicit `OPS_DATABASE_URL` wins | `env.mk` | `make test`, every service `test` target and `python-verify`, through `scripts/test_db.py`, which creates and migrates it. The store conformance suites run beside it on `<that database>_conformance` (`packages/ops_store` `backends()`), created on first use, so a session that sets its own test database also gets its own conformance database |
| `OPS_OPA_URL` | `http://127.0.0.1:8181` | settings default; `env.mk` from `OPS_OPA_PORT` | tools |
| `OPS_CORS_ORIGINS` | console ports 3016, 3017 | settings default; `env.mk` from the console ports | agents |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | unset | your secrets manager | agents (chat); unset by `verify` and by `experiment` |
| `NEXT_PUBLIC_OPS_CHAT_API_URL` | agents URL | `stack.sh`, console `run` | console |
| `KEEP_DB`, `RESET`, `CONFIRM`, `FOLLOW`, `NAME`, `UC`, `LAYER`, `E`, `ARGS`, `APPROVED_REAL_CALLS`, `BRANCH`, `PKG`, `T` | unset | you | `down`, `up`, `reset-db`, `logs`, `migration`, `usecase-test`, `experiment`, `review`, `test`; `KEEP_DATA` is accepted and changes nothing |
| `REVIEW_DIR` | `<main checkout>-review` | `git.mk` | `make review` |
| `SERVICE`, `TITLE` | unset | you | `usecase-coverage`, `usecase-new` |
| `OPS_USECASE_AGENTS_PORT`, `OPS_USECASE_TOOLS_PORT`, `OPS_USECASE_MODELS_PORT`, `OPS_USECASE_CONSOLE_PORT`, `OPS_USECASE_DB` | a free port each, and a database `ops_usecase_r<pid>_<hex>` created and dropped by the run | `packages/usecase-runner` (`isolation.ts`) | use case scripts |

## One stack, many sessions

| Gotcha | Rule |
|---|---|
| `db-up` never recreates a running PostgreSQL or OPA (`--no-recreate`) | Every checkout, worktree and verify export shares the `ops-runtime` compose project, and OPA mounts the policy folder by path; a recreate from another checkout re-mounted OPA there and dropped the review key, so every approved write was refused. After changing `compose.yaml`, recreate on purpose with `docker compose -p ops-runtime -f deploy/compose/compose.yaml up -d --force-recreate` from the main checkout |
| The live service's timer poller claims timers on whatever database it runs on | Tests never share a database with a running stack: `make test` and `make verify` use `OPS_TEST_DATABASE_URL`, and `scripts/test_db.py` refuses `ops_runtime` |
| Use-case runs from two sessions shared database `ops_usecase` and ports 8790 to 8792, so one run's services or rows broke the other's checks | Each `make usecase-test` picks its own free ports and creates its own database, dropped when it ends; set `OPS_USECASE_*` only to pin one, and `make usecase-reset` drops what a killed run left |
| Every tools-service start writes its review key and gateway policy into the OPA it is given, so with one OPA on :8181 a dev stack, another session's use case or a tree with a different policy rewrote them under a running suite, and the suite's approval tokens were refused ("not signed by the review service") | The gateway tests (agents `tests/gateway`, `tests/conformance`, tools-service `tests/`) and the use-case harness's `tools()` each start a private OPA container on a free port (`ops_service_kit.opa_server`); only the live stack uses :8181 |
| A check ran `make verify` in a tree where other sessions held uncommitted edits, so their work turned the check red | `scripts/verify-head.sh` runs `make verify` on an export of HEAD with its own test database (dropped at exit); setup takes about 10 s |
| The commit hook checks a copy of the staged tree, which is a whole uv workspace; with the checkout's `.venv` linked into it, a uv call there reinstalled every member pointing at the copy, which the hook then deleted | The copy gets no `.venv`; its Python checks run on the checkout's own interpreter, and `UV_NO_SYNC=1` keeps any uv call from installing (`scripts/tests/test_verify_staged.py`) |
| The Python services do not reload code, so after a migration the database ran a newer schema than a running agents-service (forced RLS on the run tables), and chat broke until a restart; a switch to an older branch left services on the newer code, since their start time was after its commits | `make up` stops each service whose recorded checkout or commit differs from this one in its code, or that started before the last migration, migrates, then starts them (about 5 s). `make migrate` refuses while one is stale and prints `run make up` (`scripts/tests/test_make_stack.py`) |
| `make restart SVC=tools` started tools-service on code whose migration had not run, and it crashed on a missing column until the chain was applied by hand | `make restart` applies the service's own chain between stop and start (every chain when no `SVC` is named), as `make up` does; the console has none |
| A database built by other code (another session's newer migrations, an edited chain) breaks a service that did not create it, and dropping it to recover signed everyone out and lost their data | `make up` migrates every chain in place (`scripts/schema_sync.py` reports a chain behind and continues); a chain the database holds at a revision this checkout lacks stops `make up` with the chain named and changes nothing. Only `make reset-db` (or `make up RESET=1`) drops the database: it stops this stack's Python services, drops and recreates it, and migrates from empty, asking first (`CONFIRM=yes`). uc-111 proves a person stays signed in across `make up` |
| Migration chains until launch | Each service's chain stays the one place its DDL lives (RLS, roles, functions, in order). No new downgrade code and no down-then-up tests until launch; at launch each chain is squashed into one initial revision |

## Logs and pids

| Path | Holds | Git |
|---|---|---|
| `.logs/<svc>.log` | stdout and stderr of the `make up` process | ignored |
| `.run/<svc>.pid` | its pid; `stop` kills the process group | ignored |
| `.run/<svc>.rev` | the checkout it runs from and the commit it started on | ignored |
| `.logs/offset-<n>/`, `.run/offset-<n>/` | the same for `OPS_PORT_OFFSET=<n>` | ignored |

All of these are in the main checkout, whichever worktree runs the stack.

`make up` starts only what is not already listening. A port held by a process it did not start is reported
(`3016 already served by pid N, skipping console`) and left alone; `make down` stops only processes with a pid file.
`make health` shows, per row, whether the listener belongs to `make up` or to another process.

## Ports

| Process | Port |
|---|---|
| Console (`make up`, `make dev`) | 3016 |
| Console with runtime chat (`make dev-runtime`) | 3017 |
| Embed app | 3020 |
| Agents service | 8700 |
| Platform service | 8710, 8711 |
| Tools service | 8720 |
| Models service | 8730 |
| KB, files, documents services | 8740, 8750, 8760 |
| Code runner | 8770 |
| API reference page | 8799 |
| OPA | 8181 |
| PostgreSQL | 5477 |

`OPS_PORT_OFFSET=<n>` adds n to each (a tenth of n to the mail servers' ports), with its own compose project and
data volume.

## What you type

| Task | Command |
|---|---|
| First setup | `make install` |
| Start everything | `<wrapper> -- make up` |
| Try a branch on the same ports | `make review BRANCH=<name>`; `make up` in your checkout moves the stack back |
| Start inside a devcontainer | `make up OPS_INFRA=external` |
| Is it up | `make health` |
| Watch one service | `make logs SVC=agents` |
| Restart after a settings change | `make restart SVC=agents` |
| New migration, then apply | `make migration NAME="add cases"` then `make migrate` |
| Before committing | `make verify` |
| One package's or service's tests | `make test PKG=packages/ops_access` or `make test PKG=services/agents-service` |
| Tests of what changed since `origin/main` | `make test` |
| Run the core and impacted UI use cases (about 10 minutes, one line per use case) | `make uc-impacted` |
| Run an experiment | `make experiment E=1` |
| Stop everything | `make down` (`KEEP_DB=1` keeps PostgreSQL and OPA) |

## Salesforce test sign-in

A chat script that needs a person signed in to Salesforce, or signed out and back in, runs with nobody at a browser.
The test sign-in uses Salesforce's OAuth 2.0 JWT bearer flow (RFC 7523) against an org you own.

| Task | Command |
|---|---|
| Sign a person in from keys in `.env` | `make sf-signin-env AS=<person>` |
| Keep a person's own sign-in, sign them out here, put it back | `make sf-signin-save AS=<person>`, `make sf-signin-remove AS=<person>`, `make sf-signin-restore AS=<person>` |
| Put the meeting flows' sample records in the org, or take them out | `make demo-org-seed AS=<person>`, `make demo-org-remove AS=<person>` |

`sf-signin-env` reads four keys from the stack's `.env` by name and prints none of their values:

| Key | Holds |
|---|---|
| `SF_TEST_CLIENT_ID` | The Consumer Key of an External Client App (or connected app) with the JWT Bearer Flow on |
| `SF_TEST_USERNAME` | The org user the test acts as: the Username in Setup › Advanced User Details, which is not always the email |
| `SF_TEST_JWT_KEY_FILE` | The private key whose certificate is uploaded to that app |
| `SF_TEST_LOGIN_URL` | Optional; `https://login.salesforce.com` by default, `https://test.salesforce.com` for a sandbox |

Setting up the app in Salesforce:

| Step | Where |
|---|---|
| 1. Make a key pair and a self-signed certificate | `openssl req -x509 -newkey rsa:2048 -nodes -keyout sf-jwt.key -out sf-jwt.crt -days 365 -subj "/CN=ops-ai-test-signin"`; keep the key outside the repository, mode 600 |
| 2. Create the app | Setup › External Client App Manager › New External Client App; enable OAuth with any callback URL |
| 3. Choose scopes | **Manage user data via APIs (api)** and **Perform requests at any time (refresh_token, offline_access)**. Salesforce refuses the JWT flow without the second, though the flow returns no refresh token |
| 4. Turn on the JWT flow | Flow Enablement › **Enable JWT Bearer Flow**, and upload `sf-jwt.crt` |
| 5. Pre-authorize the user | Policies › Permitted Users: **Admin approved users are pre-authorized**, then add the user's profile under Select Profiles |
| 6. Copy the Consumer Key | Settings › OAuth Settings › **Consumer Key and Secret** |

The JWT flow returns no refresh token, so the sign-in lasts as long as the org's session timeout (about an hour); run
`make sf-signin-env` again after it ends. The person is found the way `ops --as` finds them, so these targets run
only against a local stack. A chat that saves really writes to the org, so use an org that holds test data only.

## Departures from the sibling platforms

| Sibling practice | Here | Why |
|---|---|---|
| Root `help` with `##` comments and `##@` groups | Kept, shared by every Makefile through `env.mk` | One help format everywhere |
| Fragments included by concern | Kept, with `include`, not `-include` | A missing fragment should fail loudly |
| `backend` multi-process with hot reload | Dropped for `up`: plain background processes, foreground `run` per service | Two Python services and a console do not need a supervisor; `uv run` and `next dev` already reload where it matters |
| `dev-health`, `dev-logs SVC=`, `backend-down` | Renamed `health`, `logs SVC=`, `down` | One stack, so the `dev-`/`backend-` prefix adds nothing |
| `ISOLATED=1` alternate ports and compose project | Dropped for one stack per machine; `OPS_PORT_OFFSET` remains for a machine whose default ports another program holds | Several stacks at once overloaded the machine, and what ran on :3016 was rarely the branch under review |
| Adopt a server already on the port | Kept as "report and skip", never kill | A port another program holds is not this stack's to stop |
| Logs and pids in the repo | Kept: `.logs/`, `.run/` in the main checkout | Readable by the editor, ignored by git |
| `usecase-test UC= LAYER=` | Kept as the entry point; the runner is `scripts/usecase.mjs` | Same command as on the sibling platforms |
| Secrets through a named wrapper inside make | Dropped: make never calls the wrapper; you run make under it | Keeps the repo free of a vendor name and works with any secrets manager |
| `dashboard`, deploy, promote and release targets | Dropped | Nothing deploys from this repo yet |
| Hand-written per-service pass-throughs | Replaced by generated `<verb>-<svc>` | Adding a service is one line |
