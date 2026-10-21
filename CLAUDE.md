# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Ops AI is an open design for an operational AI platform for enterprises, plus working code that shows it. The console
(`apps/console/`) is a Next.js app for a fictional bank, Harbor & Pine Bank: what agents did, what is waiting on a
person, and the configuration behind both. It runs against an in-memory mock API that the backend services in
`services/` replace one area at a time. Read `.codeloop/wiki/concepts/builder-best-practices.md` before starting any card. Read `AGENTS.md` and `CONTRIBUTING.md` before changing anything; console
rules are in `apps/console/CLAUDE.md`.

## Four rules every change follows

The owner set these, and a review refuses a change that breaks one, even when a card or brief asks for it.

| Rule | What it means here |
|---|---|
| One of each thing (DRY) | One API per resource, one component per pattern, one helper per rule, one source per fact. Before writing something, find the existing one and use or extend it (`.codeloop/wiki/rulebook/review-checklist.md` §1). |
| No hard coding | Who may do what is decided only by `can()` over the roles grid and team policies, with open defaults: never a check on a role name, an owner, an id prefix or a flag in code. Agents, workflows, tools, skills, guardrails and document types are database records seeded from files, never definitions in code. Settings come from the settings class, and states, kinds and limits are named constants or settings, not literal strings scattered through code. |
| Use cases are configuration | Ops AI must serve thousands of use cases like the levy example. A use case is workflows, document types, agents, tools and settings a builder configures, never a code path, a screen or a field written for one use case. Screens and nodes are generic and read what to show from the step's settings and data; levy is one worked example among several in tests and docs. |
| Design in layers | Inside a service: domain, then app, then adapters, then api, each depending only inward. Across the product: services, then API, then SDK, then console and CLI as thin peers. Subsystems never call each other to act; workflows compose them (`service-boundaries.md`). |

## Service map

Full design: `docs/architecture/service-map.md`. `packages/` holds reusable libraries and `services/` holds
deployables. Each service is named after the console section it serves, so a page and the service behind it share a
name.

| Service | Console section | Owns | State |
|---|---|---|---|
| `platform-service` | Govern: Access, Audit log, Settings | Sign-in, sessions, tenancy, teams, roles, invites, API keys, audit. The only issuer of identity tokens; other services verify them locally through `packages/ops_identity`. Routes nothing | Prototype |
| `agents-service` | Agents, Workflows, Deployments, Skills, Chat, Assurance | Definitions, versions, publish and release gate, evals, channels, and execution: agent kernel, threads, runs, leases, timers. Runs as `api` and `worker` processes | Prototype |
| `ops_hitl` (package, planned) | Work: Cases, Reviews | Cases, queues, SLA display, Reviews, decisions, approval tokens; a shared package in the service host, owned by neither agents nor workflows | Planned; Reviews live in agents-service today (`.codeloop/wiki/concepts/reviews-and-cases.md`) |
| `tools-service` | Data Hub: Tools, Connections; tool-call Activity | Tool egress: tool modules, credentials, OPA policy, approval-token checks, call log | Prototype |
| `models-service` | AI gateway (planned in `docs/plan/ai-gateway-console.md`) | Model egress: aliases, provider keys, per-identity keys and budgets, failover | Not started |
| `kb-service` | Data Hub: Knowledge bases, Wiki | Sources, ingestion, indexing, retrieval, citations | Not started; library in `packages/ops_ingest` |
| `files-service` | Data Hub: Documents, uploads | File bytes, scanning, retention, legal hold | Prototype: runs on :8750 with its own migration chain; uploads, scan hook, versions, references, legal hold, storage settings and the file list. Retention and scan loops are planned; backends in `packages/ops_storage` |

| Package | Role |
|---|---|
| `packages/contracts` | `ops_contracts`: Pydantic models mirroring `apps/console/src/lib/types/chat.ts` by hand until generated |
| `packages/ops_service_kit` | Settings (the only place env is read), errors, ids, logging |
| `packages/ops_agent_kernel` | One agent turn on Pydantic AI: context, loop, interrupts and resume, stream events (spec 15) |
| `packages/ops_checkpointer` | LangGraph checkpointer on asyncpg with tenant row-level security |
| `packages/ops_storage` | Object storage protocol with filesystem, S3 and Azure Blob backends (ADR-0010) |
| `packages/ops_ingest` | Parsing, splitting, metadata, dedupe and source rules for knowledge ingestion |

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
  services embedded), `tools-service` and `models-service`, plus native PostgreSQL (`deploy/vm/`). Compose and Kubernetes
  (Kustomize) are optional. No service may need infrastructure beyond PostgreSQL; no dependency may be container-only.

Known departures from these rules, each a follow-up step in `docs/architecture/service-map.md`: `tools-service`
imports `ops_agents.activities` from `agents-service`; the Reviews router imports `ops_tools`; the tools service's tables
and tests live in `agents-service`; the settings default `seed_dir` points into `services/agents-service/tests/`.

## Commands

Everything runs from the root `Makefile` (`make help`); each service also has its own.

| Task | Command |
|---|---|
| Install console and Python workspace | `make install` |
| Everything a commit must pass | `make verify` |
| Whole stack in the background (dev DB, platform :8710, agents :8700, tools :8720, console :3016) | `make up`; `make health`; `make logs SVC=platform\|agents\|tools\|console`; `make down` |
| Console on the mock | `make dev` → http://localhost:3016 |
| Console with chat on the agents service | `make dev-runtime` → http://localhost:3017 |
| PostgreSQL :5477 and OPA :8181 | `make db-up` / `make db-down` |
| Migrate | `make migrate` |
| Agents service on :8700 | `make run-agents` (needs `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` for a `claude-*` alias) |
| Tools service on :8720 | `make run-tools` |
| One Python test | `cd services/agents-service && uv run pytest tests/api/test_chat.py::<test_name>` |
| Docs placement check | `pnpm check:docs` |

`pnpm verify` (the pre-commit hook) type-checks the console, runs its standards check and the docs check. The console
has no unit test runner: a console change is done when `pnpm verify` passes and every changed route renders in a
browser without console errors, including the `?mock=slow`, `?mock=error` and `?mock=empty` states.

Python is one uv workspace at the repo root (`pyproject.toml`, `uv.lock`) with ruff and strict pyright.
`make -C services/agents-service verify` runs lint, pyright, the tests and `scripts/check_standards.py` (layer order,
env read only in `ops_service_kit/settings.py`, fixtures only under `tests/fixtures`, every route authenticated).
Most tests run on in-memory SQLite with a scripted model in place of the LLM (`tests/conftest.py`);
`tests/api/test_graph_restart.py`, `tests/api/test_leases.py`, `tests/checkpointer`, `tests/gateway` and
`tests/timers` need `make db-up` and `make migrate`. Real model calls are capped at 10 per experiment unless the owner
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

Every ADR in `docs/architecture/decisions/` is an option, not a decision, until the owner confirms it. ADR-0015 keeps
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
folders carry a brief `README.md` of at most 40 lines that links into `docs/`. No dates in file names. Every doc has a
status line and is listed in `docs/README.md`. `scripts/check-docs.mjs` enforces all of this in `pnpm verify`.

Doc file names are topics; specs keep their number and ADRs their id in the title, so "spec 14" and "ADR-0005" still
resolve. Docs hold decisions, rules, facts, gotchas and evidence, not narrative. Specs follow the 11-section shape in
`CONTRIBUTING.md`. Use roles, never personal names. Say "the bank" in specs; "Harbor & Pine Bank" appears only in the
console. Mark unconfirmed claims **unverified**.
