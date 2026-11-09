# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Ops AI is an open design for an operational AI platform for enterprises, plus working code that shows it. The console
(`apps/console/`) is a Next.js app for a fictional bank, Harbor & Pine Bank: what agents did, what is waiting on a
person, and the configuration behind both. It runs against an in-memory mock API that the backend services in
`services/` replace one area at a time. Read `AGENTS.md` and `CONTRIBUTING.md` before changing anything. Every folder
has its own `CLAUDE.md` with what it owns and how to run and test it from there ([Folder guides](#folder-guides)); the
rules shared by all of them are in [Working in one folder](#working-in-one-folder). The design docs start at
`docs/README.md`.

## Four rules every change follows

| Rule | What it means here |
|---|---|
| One of each thing (DRY) | One API per resource, one component per pattern, one helper per rule, one source per fact. Before writing something, find the existing one and use or extend it. |
| No hard coding | Who may do what is decided only by `can()` over the roles grid and team policies, with open defaults: never a check on a role name, an owner, an id prefix or a flag in code. Agents, workflows, tools, skills, guardrails and document types are database records seeded from files, never definitions in code. Settings come from the settings class, and states, kinds and limits are named constants or settings, not literal strings scattered through code. |
| Use cases are configuration | Ops AI must serve thousands of use cases like the levy example. A use case is workflows, document types, agents, tools and settings a builder configures, never a code path, a screen or a field written for one use case. Screens and nodes are generic and read what to show from the step's settings and data; levy is one worked example among several in tests and docs. |
| Design in layers | Inside a service: domain, then app, then adapters, then api, each depending only inward. Across the product: services, then API, then SDK, then console and CLI as thin peers. Subsystems never call each other to act; workflows compose them (`docs/architecture/service-map.md`). Anything that may later live outside us (a vault, models, search) sits behind a port with ours as one adapter. |


## Service map

Full design: `docs/architecture/service-map.md`. `packages/` holds reusable libraries and `services/` holds
deployables. Each service is named after the console section it serves, so a page and the service behind it share a
name.

| Service | Console section | Owns | State |
|---|---|---|---|
| `platform-service` | Govern: Access, Audit log, Settings | Sign-in, sessions, tenancy, teams, roles, invites, API keys, audit. The only issuer of identity tokens; other services verify them locally through `packages/ops_identity`. Routes nothing | Prototype |
| `agents-service` | Agents, Workflows, Deployments, Skills, Chat, Assurance | Definitions, versions, publish and release gate, evals, channels, and execution: agent kernel, threads, runs, leases, timers. Runs as `api` and `worker` processes | Prototype |
| `ops_hitl` (package, planned) | Work: Cases, Reviews | Cases, queues, SLA display, Reviews, decisions, approval tokens; a shared package in the service host, owned by neither agents nor workflows | Planned; Reviews live in agents-service today (`docs/architecture/human-in-the-loop.md`) |
| `tools-service` | Data Hub: Tools, Connections; tool-call Activity | Tool egress: tool modules, credentials, OPA policy, approval-token checks, call log | Prototype: :8720, own migration chain |
| `models-service` | AI gateway (`docs/plan/ai-gateway-console.md`) | Model egress: aliases, provider keys, per-identity keys and budgets, failover | Prototype: :8730, started by `make up`, own migration chain |
| `kb-service` | Data Hub: Knowledge bases, Wiki | Sources, ingestion, indexing, retrieval, citations | Prototype: :8740, on `packages/ops_ingest`, uploads through files-service |
| `files-service` | Data Hub: Documents, uploads | File bytes, scanning, retention, legal hold | Prototype: :8750 with its own migration chain; uploads, scan hook, versions, references, legal hold, storage settings and the file list. Retention and scan loops are planned; backends in `packages/ops_storage` |
| `documents-service` | Data Hub: Documents | What is read from a file: layouts, extractions, document types, samples, corrections; never holds bytes | Prototype: :8760, reads bytes through files-service |
| `runner-service` | Code tools | Python functions of code tools on WASM, with no network and no secrets | Prototype: :8770, no database |

Each package's own `CLAUDE.md` holds its contract; `packages/CLAUDE.md` holds the rules every package follows.

| Package | Role |
|---|---|
| `packages/contracts` | `ops_contracts`: Pydantic models mirroring `apps/console/src/lib/types/chat.ts` by hand until generated |
| `packages/ops_service_kit` | Settings (the only place env is read), logging, errors, the response envelope and the OpenAPI gate |
| `packages/ops_identity` | Who is calling: a platform token, API key or service token resolved to a Principal, team chosen, key scopes enforced |
| `packages/ops_access` | What a caller may do: the area and action catalogue, built-in roles and `can()` |
| `packages/ops_policy` | Trust primitives: canonical JSON, input hashes, signed tokens, step-up tokens; no rules |
| `packages/ops_store` | The store seam: database guarantees, the Repository protocol, ports and their conformance suites |
| `packages/ops_engine` | Workflow runner: node type registry, definitions, the LangGraph compiler, step journal, work queue and worker loop |
| `packages/ops_agent_kernel` | One agent turn on Pydantic AI: context, loop, interrupts and resume, stream events (spec 15) |
| `packages/ops_checkpointer` | LangGraph checkpointer on SQLAlchemy Core, on PostgreSQL and SQL Server, with tenant and team isolation |
| `packages/ops_storage` | Object storage protocol with filesystem, S3 and Azure Blob backends (ADR-0010) |
| `packages/ops_ingest` | Parsing, splitting, metadata, dedupe and source rules for knowledge ingestion |
| `packages/ops_extract` | Extracted-field checks: confidence from the quote, value type and page reading, and whether a person must check it |
| `packages/ops_email` | Email in and out behind two protocols, with Graph, SMTP, Resend and dev fake providers |
| `packages/ops_signin` | Sign-in protocols with no service rules: passwords, OIDC with PKCE, SAML, DNS domain proof, a fake identity provider |
| `packages/ops_plugin_sdk` | What a plugin is built with: `plugin.yaml`, `@tool` and `Context`, the shared loader, the `opsai plugin` verbs |
| `packages/ops_metering` | Model usage accounting: usage rows, prices, cost, totals and budget checks; no I/O |
| `packages/ops_pii` | Masking of personal data in what people see, in whole text or streamed |
| `packages/ops_files_client`, `packages/ops_documents_client` | Typed clients other services use to reach files-service and documents-service with a service token |
| `packages/usecase-runner` | TypeScript: resolves a use case and layer to its script, runs it and reports PASS or FAIL per check |

Rules that hold across services:

- Every service can be embedded in the gateway process or deployed alone, chosen by `OPS_ENABLED_SERVICES`.
  Production runs `tools-service` and `models-service` on their own, so egress stays separate from agent workers.
- Tool calls and model calls are different operations and go through different services. Channels (mailbox, widget,
  MCP, API) are inbound triggers and belong to `agents-service`.
- Inside a service the code is an onion: `domain` → `app` (usecases, ports) → `adapters` → `api`, imports pointing
  inward only. A service never reads another service's tables. `agents-service` is not yet in this shape.
- A package holds no one service's business rules and never imports a service; it receives what it needs as
  arguments or run config. Package names describe what the library does (no `shared`, `common`, `utils`).
- Every release must run on one virtual machine with no container runtime: systemd units for the gateway (other
  services embedded), `tools-service` and `models-service`, plus native PostgreSQL. That target is designed and
  `deploy/vm/` does not exist yet. Compose and Kubernetes (Kustomize) are optional. No service may need infrastructure
  beyond PostgreSQL; no dependency may be container-only.

Known departures from these rules, each a follow-up step in `docs/architecture/service-map.md`: `tools-service`
imports `ops_agents.activities` from `agents-service` (`services/tools-service/src/ops_tools/registry.py:14`,
`tools.py:11`, `__main__.py:16`); the gateway tests still live in `services/agents-service/tests/gateway`; the settings
default `seed_dir` points into `services/agents-service/seed/`
(`packages/ops_service_kit/src/ops_service_kit/settings.py:26`).

## Commands

Everything runs from the root `Makefile` (`make help`); each service also has its own (`make -C services/<x> help`).
How the make files are laid out and every variable they read: `docs/architecture/make.md`.

| Task | Command |
|---|---|
| Install console and Python workspace | `make install` |
| Whole stack in the background (database, every service, worker, console :3016, embed :3020) | `make up`; `make health`; `make logs SVC=<svc> FOLLOW=0`; `make ports` |
| Run someone's branch on the same stack | `make review BRANCH=<name>`; `make up` in your checkout moves the stack back |
| Console on the mock, no services | `make dev` → http://localhost:3016 (foreground; not while `make up` holds :3016) |
| Call a route or drive an area as a seeded person | `make api GET /v1/me AS=viewer`, `make kb-search …`, `make chat …` ([Calling the API as a person](#calling-the-api-as-a-person)) |
| Tests for what you changed | `make test PKG=services/<x> T=tests/<file>`; `make test` runs what changed since `origin/main` |
| One use case | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui` |
| Console gate | `pnpm verify` |
| Everything a commit must pass (CI runs it on every PR) | `make verify` |
| Regenerate OpenAPI documents and SDKs after a route change | `make openapi` |
| Migrate the stack's database | `make migrate` (`make up` does it too) |

`pnpm verify` (part of the pre-commit hook) type-checks the console and the embed app, runs the console's standards
check and its unit tests (`node --test 'src/**/*.test.ts'`), then the docs and public-path checks. A console change is
done when `pnpm verify` passes and every changed route renders in a headless browser without console errors, including
the `?mock=slow`, `?mock=error` and `?mock=empty` states (`apps/console/CLAUDE.md`).

Python is one uv workspace at the repo root (`pyproject.toml`, `uv.lock`) with ruff and strict pyright.
`make -C services/agents-service verify` runs lint, pyright, the tests and `scripts/check_standards.py` (layer order,
env read only in `ops_service_kit/settings.py`, fixtures only under `tests/fixtures`, every route authenticated).
Most tests run on in-memory SQLite with a scripted model in place of the LLM (`tests/conftest.py`);
`tests/api/test_graph_restart.py`, `tests/api/test_leases.py`, `tests/checkpointer`, `tests/gateway` and
`tests/timers` need `make db-up` and `make migrate`. Real model calls are capped at 10 per experiment unless a maintainer
approves more.

Settings use the `OPS_` prefix (`OPS_DATABASE_URL`, `OPS_PORT`, `OPS_MODEL_ALIAS`).
Keys come from the environment or a gitignored `.env` (contract: `.env.example`); never commit a `.env`.

`services/files-service/` and `packages/ops_ingest/` are workspace members with their own tests, run by `make verify`;
LocalStack and Azurite tests skip when those containers are not running.

## Architecture

The target platform (`docs/architecture/overview.md`) has six layers. Each can be replaced without rewriting the
others:

| Layer | Role |
|---|---|
| Authoring | The console; edit classes decide what a save does |
| Workflow definition | Declarative JSON graph, immutable once published, identified by `(workflowId, version, digest)` |
| Compiler and registry | Validates, pins every reference, computes the risk tier, emits an execution plan |
| Execution engine | Walks any plan behind one `Engine` interface (ADR-0015). Workflow definitions are data, so authors never write engine code |
| Activities | Agent turns, tool calls, knowledge queries, case operations, evidence writes |
| Gateways | The only egress: `tools-service` for tool calls, `models-service` for model calls |

Every ADR in `docs/architecture/decisions/` is a proposal until a maintainer accepts it. ADR-0015 keeps
the engine open: Temporal or LangGraph on PostgreSQL, chosen per deployment. Do not write code or docs that treat one
engine as settled. A spec that needs a decision changed proposes a new ADR under "Open questions" instead of
re-deciding it inline.

### Console

Layers import in one direction, and `apps/console/scripts/check-standards.mjs` enforces part of this:
types (`src/lib/types`) → API contract and clients (`src/lib/api`) → hooks (`src/hooks`) → components → pages
(`src/app`). Fixtures live only in `src/lib/api/mock/`.

- `OpsApi` (`src/lib/api/contract.ts`) is the one interface screens read through. Each area has an
  `<area>-contract.ts` and `<area>-http.ts`; the mock implements the same contract.
- Only `src/lib/api/index.ts` reads env. `NEXT_PUBLIC_OPS_API_URL` moves every area to HTTP;
  `NEXT_PUBLIC_OPS_CHAT_API_URL` moves only chat to the agents service.
- Responses use the `{ success, data }` envelope. Counts and totals come from the API, never from a component.
- Adding data: type → contract → HTTP client → mock → hook.

### Agents service

The agents service runs an agent (a one-node wrapper graph), a workflow and a chat session as the same object: a
graph on a thread. One call family does the work: create a thread, run or resume it with a stream, read its state. A
human step pauses the graph with an interrupt, and the graph resumes only through a review decision. Tool calls carry
an approval token bound to the input hash (ADR-0005) and the run's lease generation, and the tools service rejects
stale ones. LangGraph on PostgreSQL is the engine built first; Temporal would sit behind the same calls.

Its code is one module, `ops_agents`, with three layers (`services/agents-service/src/ops_agents/`): `api` (FastAPI
app, routers, chat turns, leases, sweeper, timers), `graphs` (graphs, JSON definitions, versions) and `activities`
(tool, knowledge and tools-service calls). Layer order, enforced by `check_standards.py`: `ops_contracts` →
`ops_service_kit` → `ops_agent_kernel` → `ops_agents.activities` → `ops_checkpointer` → `ops_agents.graphs` →
`ops_tools` → `ops_agents.api`.

Its chat API (`/chat/*` and `/v1/chat/*`) implements the console's chat contract. Graphs run on four calls that
mirror LangGraph Server: `POST /v1/threads`, `POST /v1/threads/{id}/runs/stream`, `GET /v1/threads/{id}/state`,
`GET /v1/threads`. Where the code deliberately differs from the specs: `docs/services/agents-service/overview.md`.

The graph prototype, version pinning, the checkpointer, leases and timers are experiments. They prove the shape
works, not that it is ready for production. Each experiment is a script in `services/agents-service/experiments/`
plus a topic-named write-up in `docs/services/agents-service/experiments/` of under 60 lines: the verdict, the facts
and numbers that support it, the gotchas, and what it feeds. Its code stays only while `make verify` is green. The console's mock contracts
remain the source of truth for the API.

## Docs

Full docs live only under `docs/`, in folders that map to the repo (`CONTRIBUTING.md`, "Where docs live"); code
folders carry a brief `README.md` of at most 40 lines that links into `docs/`, and a `CLAUDE.md` with the agent
guidance for that folder (no length limit; under `docs/` the guidance goes in the folder's `README.md`, since
`check-docs.mjs` refuses any other upper-case name there). No dates in file names. Every doc has a
status line and is listed in `docs/README.md`. `scripts/check-docs.mjs` enforces all of this in `pnpm verify`.

Doc file names are topics; specs keep their number and ADRs their id in the title, so "spec 14" and "ADR-0005" still
resolve. Docs hold decisions, rules, facts, gotchas and evidence, not narrative. Specs follow the 11-section shape in
`CONTRIBUTING.md`. Use roles, never personal names. Say "the bank" in specs; "Harbor & Pine Bank" appears only in the
console. Mark unconfirmed claims **unverified**.

## Working in one folder

A folder's `CLAUDE.md` says what the folder owns and how to run, test and lint it. The rules in this section hold in
every folder, and the folder guides link here instead of repeating them.

### Onion order

A change moves inside out and lands in one change across the layers it touches: service, then its OpenAPI document,
then the SDKs, then the CLI and console, which are thin peers over the SDK. Inside a service the order is `domain` →
`app` → `adapters` → `api`. A lower layer never imports a higher one: packages never import a service, and services
never import each other's code (the one departure is listed under [Service map](#service-map)). `.importlinter`
(`uv run lint-imports`) and `services/agents-service/scripts/check_standards.py` enforce part of this.

| Layer | Folder | After changing it |
|---|---|---|
| Service route, DTO or rule | `services/<x>/` | `make test PKG=services/<x> T=tests/<file>` |
| OpenAPI document | `services/<x>/openapi.json` | `make openapi` writes every service's document, then regenerates the SDKs |
| SDKs | `sdk/python`, `sdk/typescript` | `make sdk-verify` (the generated layer matches the documents, both test suites pass) |
| Console | `apps/console/` | `pnpm verify`, then the changed routes in a headless browser |

A screen that needs data the API does not return gets the route first. Counts, joins and totals come from the API,
never from the console.

### One local stack

One stack runs per machine, on fixed ports (`make ports`), from the checkout that last ran `make up`. Its logs, pids
and data live in the main checkout (`.logs/`, `.run/`, `.data/`), which every worktree shares.

| Task | Command |
|---|---|
| Start or bring up to date (migrates, then restarts only what changed) | `make up` |
| Run another branch on the same ports | `make review BRANCH=<name>` |
| Is everything up | `make health` |
| One service's log | `make logs SVC=agents FOLLOW=0` |
| Restart one service, migrating it first | `make restart SVC=tools` |

Never start a second stack or run a service by hand on a port the stack holds. Tests never touch the stack's
database: each run makes a throwaway one (`OPS_TEST_DATABASE_URL`, `scripts/test_db.py`), and a use case starts its
own services on free ports. `make reset-db` and `make up RESET=1` wipe the database every checkout shares. Detail and
gotchas: `docs/architecture/make.md`.

### Calling the API as a person

Test and call the system through the make targets (`api`, `chat`, `kb-*`, `apps-*`, `tools-*`, `runs-*`, `tasks-*`,
`memories-*`, `test-data-clean`), with `AS=` to act as a person, instead of ad-hoc scripts or SQL; read the database
only to diagnose. Every target, variable and the test-data rule:
[make/CLAUDE.md](make/CLAUDE.md#calling-the-api-as-a-person-devmk-climk).

### Tests

| Rule | Detail |
|---|---|
| Run the tests for the files you changed | `make test PKG=packages/<x>` or `PKG=services/<x>`, with `T=` naming files; `make test` with no `PKG` runs the suites of what changed since `origin/main` and every member that depends on a changed package (`scripts/verify-changed.sh`). `T=` reaches pytest for packages and for agents-service and tools-service only; the other service Makefiles ignore it and run the whole suite, so name files there with `PYTEST_ADDOPTS=tests/<file>.py make test PKG=services/<x>` |
| Full suites run in CI | `.github/workflows/ci.yml` runs everything `make verify` runs on every pull request; run `make verify` locally to reproduce a CI failure |
| Use cases | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui`; registry and rules in `docs/usecases/README.md` |
| Scripted model | Tests and use cases run on the scripted model with model keys removed; real model calls are capped at 10 per experiment unless a maintainer approves more |
| One test per failure mode | Name the ways the change can break, write one test for each, and watch each new test fail once before trusting it |

### Commits

`pnpm install` in the main checkout installs three hooks from `.githooks/` (`scripts/install-hooks.sh`). Never bypass
them with `--no-verify`. `scripts/git-rules.py`, run as a Claude Code PreToolUse hook on Bash, refuses `git stash`, hard
resets, `git clean`, skipped hooks, force pushes and pushes to `main`; `make git-rules` prints the rules and self-tests
them.

| Hook | Checks |
|---|---|
| `pre-commit` | The gates the staged files need, on an export of the staged content (`scripts/verify-staged.sh`) |
| `commit-msg` | `scripts/commit-message-check.mjs`: `type(scope): subject` of at most 72 characters; a body of at most three lines and 320 characters saying why the old behaviour was wrong and what ran to prove the fix; no first person, narration, history or filler words. Then `scripts/changelog-check.mjs` |
| `pre-push` | ruff check and format on the Python files the pushed commits change |

A `feat` or `fix` commit that changes `apps/` or `services/` carries a `Changelog: <topic>` trailer and stages
`changelog/<topic>.json` in the same commit. The entry is what a person using the console reads under What's new:
`{"date": "YYYY-MM-DD", "title": "…", "description": "…", "tag": "new|improved|fix"}`, a title of at most 60
characters, a description of one or two sentences, and no file paths, file names, ids, commit hashes or first person
(`make changelog-verify` checks every entry).

`make commit FILES='a.py b.md' MSG='fix(tools): fill query placeholders' CHANGELOG=query-placeholders` commits only the
named files through both hooks, from HEAD plus those files; `make whats-mine FILES=…` shows what it would commit, and
`make my-hunks` with `make commit-hunks` commit your hunks of a file others are also editing.

## Folder guides

| Folder | Guide |
|---|---|
| `apps/console/` | `apps/console/CLAUDE.md`: layers, components, states, copy, checks |
| `apps/docs/`, `apps/embed/` | `apps/docs/CLAUDE.md`, `apps/embed/CLAUDE.md` |
| `services/` and each `services/<x>/` | `services/CLAUDE.md`, then the service's own |
| `packages/` and each `packages/<x>/` | `packages/CLAUDE.md`, then the package's own |
| `sdk/` | `sdk/CLAUDE.md`: both SDKs, the generated layer and the CLI |
| `deploy/` | `deploy/CLAUDE.md`, then each target's `README.md` or `CLAUDE.md` |
| `make/` | `make/CLAUDE.md`: the fragments and the API-as-a-person targets |
| `scripts/` | `scripts/CLAUDE.md`: what each group of scripts does and its tests |
| `docs/usecases/` | `docs/usecases/README.md` |
| `examples/` | `examples/CLAUDE.md` |
| `plugins/` | `plugins/README.md`: the install's plugins folder, ignored by git apart from its README |

Folders without a guide of their own:

| Folder | Holds | Change it with |
|---|---|---|
| `changelog/` | One What's new entry per file ([Commits](#commits)) | `make changelog-verify` |
| `roadmap.json` | Coming next items the console shows | `make changelog-verify` |
| `config/` | The leak scan's patterns and baseline (`scripts/leak_scan.py`, `.github/workflows/leak-scan.yml`) | `uv run pytest -q scripts/tests/test_leak_scan.py` |
| `.githooks/` | The three hooks above | `bash scripts/tests/test-verify-staged.sh` |
| `.github/` | CI workflows; `copilot-instructions.md` and `prompts/` are generated from `AGENTS.md`, this file's "Four rules" section and `docs/guide/skills/` | `python3 scripts/agent_skills.py`, then `python3 scripts/agent_skills.py --check` |
| `.devcontainer/` | The development container, running the stack with `OPS_INFRA=external` | `make skills-proof` runs every developer skill in a fresh one |
