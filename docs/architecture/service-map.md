# Service map

Status: current, 2026-10-18. Approved; where a row says designed or planned, it is the target and is not
built yet. The target design is [workflows and agents](../design/workflows/workflows-and-agents.md); specs 14 and 17 defer to this page
where they differ.

## Services

![Callers reach agents-service; every tool and model call leaves through tools-service and models-service; files and documents are separate services](../diagrams/component-map.svg)

Ops AI is one platform. Agents and workflows are two ways of running work; both use the shared services (Reviews,
Cases and work items, triggers, identity, knowledge, files) and the two gateways (data and AI). Each service is named
after the console section it serves. `packages/` holds reusable libraries; `services/` holds deployables.

| Service | Console section | Owns | State |
|---|---|---|---|
| `platform-service` | Govern: Access, Audit log, Settings | Sign-in, sessions, tenancy, teams, roles, audit, API keys; later notifications, usage, search. The only issuer of identity tokens (asymmetric, public keys at a JWKS route); every service verifies locally through `ops_identity`. Routes nothing and hosts nothing; holds no model or tool credentials | In code: `services/platform-service`, `packages/ops_identity` (`docs/services/platform-service/overview.md`); adoption by agents and tools next |
| `agents-service` | Agents, Workflows, Deployments, Skills; Chat; Assurance; Work: Cases, Reviews | Definitions and versions, publish and release gate, evals, channels (mailbox, widget, MCP, API), execution: kernel turns, threads, runs, leases, timers, usage and thread budgets. Hosts the workflow runner (`ops_engine`) and, today, Reviews, Cases and decisions | Prototype in `services/agents-service` |
| `tools-service` | Data Hub: Tools, Connections; tool-call Activity | Tool egress: tool modules, connections (how each system is signed in to, per test and production, with their tokens), credentials, mock answers in test, OPA policy, approval-token checks, call log and dedupe | Prototype in `services/tools-service` |
| `models-service` | AI gateway (`docs/plan/ai-gateway-console.md`) | Model egress: aliases, provider keys, per-key ledgers and budgets, logging, failover, in front of Portkey (ADR-0008) | First slice built in `services/models-service` on :8730 (`docs/services/models-service/overview.md`); opt-in through `OPS_MODELS_URL`, and `make up` does not start it |
| `kb-service` | Data Hub: Knowledge bases, Wiki | Sources, ingestion, indexing, retrieval, citations, freshness | First slice built in `services/kb-service` on :8740 (`docs/services/kb-service/overview.md`), started by `make up`; uses `packages/ops_ingest` |
| `files-service` | Data Hub: Files, uploads | File bytes: upload, download, type judged from the bytes, scanning, dedupe, retention, legal hold, WORM evidence | First slice on :8750: uploads, proxy routes on the local backend, dedupe, downloads, legal holds, scan hook; client in `packages/ops_files_client` |
| `documents-service` | Data Hub: Document types; the file page's Preview and Extract; the Human Task read check | What is read from a file: page layout (text blocks with boxes), classify and split, extractions with cited positions, document types and their versions, samples, templates, corrections, per-field accuracy. Never holds bytes | Built on :8760 with its own migration chain, on `packages/ops_extract` ([documents service](../services/documents-service/overview.md)) |
| `runner-service` | Data Hub: Tools (a code module's functions) | Runs a code tool's Python function in a sandbox: CPython on WASM, no network, no secrets, memory, time and call limits; `ops.call` goes back through tools-service as the caller | First slice on :8770, started by `make up`; no database (`docs/services/runner-service/overview.md`) |

There is no human-in-the-loop service. Reviews, Cases and work items move into the `ops_hitl` package (planned), and
schedule, webhook, email and poll triggers into the `ops_triggers` package (planned); agents-service serves both today.

Tool calls and model calls go through different services: a tool call acts on a bank system and needs an approval
token per call; a model call spends budget and needs a key per identity. Channels start runs, so they belong to
`agents-service`.

Files and documents are separate because they change for different reasons. Files keeps bytes safe and decides how long
they live; documents decides what the bytes say, calls models and learns from corrections. A team can store files with
no extraction, and extraction can be scaled, priced and replaced without touching storage.

## Who calls whom

Every call goes through a typed client with a service token and the caller's team. No service reads another's tables.

| From | To | Why | Through | Scope |
|---|---|---|---|---|
| console | every service | Pages read and write through each service's API | the SDK | the person's token |
| agents-service (runs, channels) | files-service | An email attachment or chat upload is stored; a step reads a file | `ops_files_client` | `files:create`, `files:view` |
| agents-service (Extract step, `extract_document` tool, read check) | documents-service | A workflow step or tool reads a document; a Human Task shows and corrects fields; a purge step removes what was read from a deleted file | `ops_documents_client` | `documents:view`, `documents:run`, `documents:delete` |
| documents-service | files-service | Reads input bytes, and a sample's file reference; a file the caller's team cannot see is 404 | `ops_files_client` | `files:view`, `files:edit` (sample reference) |
| documents-service | models-service | Classify, extract and the one re-read of failed fields on the model path, charged to the caller's team; page images only where the type version, the team's `pageImages` policy and the alias's image clearance all allow | models client | `files:extract` purpose, budget per team |
| documents-service | platform-service | Reads the workspace floor and the team's `pageImages` policy live on each read; an unreadable policy counts as off | service token | `settings:view` |
| `file_deleted_purge` on `file.deleted` | documents-service | Retention and legal-hold deletes remove the derived layout, extractions and samples. files-service emits the event and calls nobody | service event | `documents:delete` |
| any service | agents-service | Reports a service event; the tenant's handler for it runs (below) | `POST /v1/events`, through the `ops_store.outbox` relay | `events:emit` |
| kb-service | files-service | Knowledge uploads are stored as files | `ops_files_client` | `files:write` |
| agents-service | tools-service | Every tool call to a bank system, with its approval token and the run's environment (production for live runs and chats, test otherwise) | tools client | approval token per call |
| agents-service | tools-service | A write's policy (access, approvers, step-up; the approving team it still answers is ignored) for each review it draws or decides, `GET /v1/tools/{name}`; read once per tool per request (`tool_access.one_read_per_tool`), so a changed policy applies from the next request | tools client | service token |
| agents-service, kb-service, documents-service | models-service | Every model call, with its alias and key | models client | key per identity |
| tools-service | models-service | Check before sending: one judgement per payload and policy version of a write against the team's sending policy | `ops_service_kit.model_calls.StructuredCalls` | its own key, `tools:check` |
| tools-service | platform-service | Reads `checkBeforeSend`, `toolWritesNeedApproval` and `requesterMayDecide` live on each call; an unreadable `checkBeforeSend` counts as on (register E39) | service token | `settings:view` |
| outside assistants (Claude Code, Cursor) | tools-service | The team's read tools over MCP at `/mcp/test/{team}` through the same call path as `POST /v1/calls` | MCP streamable HTTP | an API key or a person's token of that team holding `tools.run` |
| an agent, an outside caller | agents-service | One workflow AI step's answer (Classify, Summarise, Extract from text, Draft) as a step would give it, under the team's `aiSteps` | `POST /v1/ai-steps/{step}` | `workflows.run` in the team |
| platform-service | agents-service | Before a team is deleted or its workspace closed: the team's runs in progress and the names of its live workflows, `GET /v1/teams/usage` for the token's team only. No answer refuses the delete or close (503 `usage_unavailable`) | service token naming the team | `workflows:view` |
| every service | platform-service | Identity tokens checked locally against its public keys | `ops_identity` | none |

### Service events

A service reports what happened as a named event with a key; agents-service starts the tenant's handler for it, on
the event's team, with run key `<event>:<key>` so a repeat returns the same run and a repeat after a failure starts the
next attempt. The handlers are ordinary workflows shipped in `services/agents-service/seed/event_workflows.json`,
published to each tenant on its first event, owned by no team, and edited through publish review like any other. An
event nobody handles is recorded `unhandled`.

| Event | Emitter | Handler | Status |
|---|---|---|---|
| `tool_access.requested` | tools-service (`services/tools-service/src/ops_tools/modules/review_events.py:12`) | `tool_access_request`: the workflow's tool access review | built |
| `module_review.requested` | tools-service | The tool module's publish review | planned |
| `file.deleted` | files-service | `file_deleted_purge`: purge what documents-service derived from the file | built |
| `file.read_requested` | files-service | `system_extract`: read the file and save what was read on it | built |
| `extraction.corrected` | documents-service | `extraction_corrected_save`: save the corrected read on its file, so the files list's Read as and to-check count follow it; sent only for the file's newest read | built |
| `task.requested` | agents-service itself, from `POST /v1/tasks` (`api/routers/tasks.py:41`), with a new key per post | `api_task`: a Human Review step on the posted task type; the task id is the run id | built |

A service reports only the events this catalogue gives it (`EVENT_OWNERS` in agents-service `api/service_events.py`:
tools-service `tool_access.`, `tool_module.` and `module_review.`; files-service `file.`; documents-service
`extraction.`; agents-service `task.`; 403 `event_not_owned` otherwise), for the team its token names (403
`team_mismatch`).

Subsystems compose through workflows, not through each other (rulebook `service-boundaries.md`). Documents reads
its input from files and never the other way; storing results on a file, review and purge are workflow steps. The engine and the agent kernel never import `ops_extract`; an Extract node and the `extract_document` tool are
thin calls on the documents API (review checklist §3, "A node or tool with no API behind it").

### Background processes

Work that runs without a person asking is one list, `PROCESSES` in `packages/ops_store/src/ops_store/background.py`
(an earlier change). Each process runs once for the account, finds its next job across teams, and does that job inside the job's
team. A loop starts only through `background.run`, which retries a failed pass after 1 s doubling to 60 s and writes a
heartbeat at most every 10 s and on every error; `test_background_registry.py` fails on a loop not on the list.

| Process | Service | Heartbeat kept in | Jobs logged |
|---|---|---|---|
| Workflow worker, sweeper, timer poller, memory clean-up, mail listener, event workflows | agents-service | `background_heartbeats` (one row per process instance) | `background_jobs`, in the job's team (memory clean-up: none) |
| File hand-off, document hand-off, tool events (outbox relays), document reading | files, documents, tools | the process's memory | none: a failed hand-off shows as the heartbeat's last error and on its outbox row |

Each service answers `GET /health/background` (states and counts, no record's data), which `make health` and the
staging check read; late after two gaps and stopped after five, a gap being the interval or the 10 s write gap,
whichever is longer. Agents-service `GET /v1/background` serves Govern > Background to account admins only, reading
its own tables and only reading the other services' `/health/background`; a team reads its own jobs in Activity.

## Roadmap

| Service | Built now | Next | Later |
|---|---|---|---|
| `platform-service` | Sign-in, teams, roles, audit, API keys, policies | Provider keys entered in the console, email invites | Notifications, usage, search |
| `agents-service` | Agents, workflows, runs, chat, Activity, Human Tasks, Cases; channels (API with scoped keys, chat, email from IMAP, Gmail and Microsoft 365) on one channel API (`/v1/channels`: list, health, rename, pause, websites, serves, retire); service events and the seeded workflows that handle them | Chat channels are still created and listed on `/v1/widget-deployments`; Activity for a channel follows the runs its emails started | `ops_hitl` and `ops_triggers` move into packages; worker scales apart |
| `tools-service` | Registry, imports, connections and their sign-in, secrets, egress, mock answers, limits, approval tokens | Grants | Stands alone without agents fixtures |
| `models-service` | Aliases, completions, refusals | Budget per team, keys from Secrets | Per-key ledger, failover |
| `kb-service` | Sources, ingestion, retrieval with citations | Freshness | Wiki |
| `files-service` | Storage, dedupe, holds, type from bytes, OCR for scans | Purge to documents on delete | Retention jobs, resumable uploads, virus scan |
| `documents-service` | Extraction and document types, on :8760 with its own chain | layout, cited boxes, templates, classify, file page, proof on the restraining-notice samples | Tables, split, accuracy from corrections |
| `runner-service` | Python functions on WASM, `ops.call` to bound tools, secret handles | none | TypeScript, curated packages, gVisor and Firecracker backends, test cases at publish |
| `ops-host` | none | none | Starts any set of services in one process |

Dev ports: platform 8710, agents 8700, tools 8720, models 8730, kb 8740, files 8750, documents 8760, runner 8770, console 3016.

## Naming

One short name runs through every layer, so a service can move to its own repository without renames.

| Layer | Pattern | Example |
|---|---|---|
| Folder and repository | `services/<x>-service` | `services/agents-service` |
| Python distribution | `ops-<x>-service` | `ops-agents-service` |
| Python module | `ops_<x>` | `ops_agents` |
| Docs | `docs/services/<x>-service/` | `docs/services/agents-service/` |
| Image, Kubernetes base, systemd unit | `<x>-service` | `agents-service` |

Short names: `platform`, `agents`, `tools`, `models`, `kb`, `files`, `documents`. Console labels keep their product names.
Settings read the `OPS_` prefix from one shared class; per-service prefixes (`OPS_<X>_`) need per-service settings
classes (designed).

## Specs per service

| Service | Specs and decisions |
|---|---|
| `platform-service` | [sign-in library](../packages/ops_signin/overview.md); ADR-0004, ADR-0013 |
| `agents-service` | [agents and workflows](../console/agents-and-workflows.md) (including cases, queues, SLAs); [ADR-0012 Assurance: governance and testing as one system](decisions/assurance.md) (including Reviews); [chat in the console](../console/chat.md); the model-risk spec; [agent guardrails and skills](agent-guardrails.md); [agent guardrails and skills](agent-guardrails.md); specs 14–17; [tool system design](../design/tools/tool-system.md) (mailbox); ADR-0001, ADR-0003, ADR-0005, ADR-0012, ADR-0014, ADR-0015, ADR-0016 |
| `tools-service` | [tool system design](../design/tools/tool-system.md); ADR-0005 |
| `models-service` | [tool system design](../design/tools/tool-system.md); ADR-0008 |
| `kb-service` | [kb-service](../services/kb-service/overview.md); ADR-0006 |
| `files-service` | [files](../services/files-service/overview.md); ADR-0006, ADR-0010 |
| `documents-service` | [documents service](../services/documents-service/overview.md); sample documents and their test cases in `docs/services/documents-service/` (with the move) |
| `runner-service` | [runner service](../services/runner-service/overview.md); data gateway spec section c |

## Decisions

| Decision | Detail |
|---|---|
| Definitions and execution in one service | Agents, workflows and their runs are one context in the console. Run load is handled by a `worker` process type that scales apart from `api` (designed) |
| Chat lives in `agents-service` | Chat sessions, threads and messages belong to `agents-service`; replaces the default in spec 14 Q2 |
| Definitions are pinned per thread | Immutable versioned JSON definitions with a digest (ADR-0003); each thread compiles and pins `(definition, version, digest)`, so the pin survives a republish |
| Human in the loop is a shared package | `ops_hitl` (planned) holds Reviews, Cases, work items and the token signing key behind its own API, so agents and workflows decide through one queue; agents-service hosts it |
| Services are independent of processes | A process is one copy of `ops-host`, which starts any set of services: all in one process for dev and tests, split by service in production. Planned as the first part of version 1 |

## Contracts that cross services

| Contract | Rule |
|---|---|
| SLA timers | The step's timeout outcome is pinned in the plan (spec 16, ADR-0005). The agents worker owns the timers table, poller and resume and decides from the pinned plan; the Reviews code (`ops_hitl` once it moves) learns the outcome afterwards to notify and record it |
| Decide then resume | The Reviews code records the decision and mints the token, then resumes the thread with the decision id as idempotency key; a failed resume is retried with the same id and resumes once |
| Fencing | Every tool call carries the run's lease generation; the checkpointer and tools-service refuse a stale one. No shared table |
| Data ownership | A service never reads another service's tables |
| Key budgets | agents-service asks a key-admission port before opening a thread (429 `key_budget_exhausted` on refusal); models-service will answer it from its ledger |

## Layering

Inside a service, dependencies point inward: `domain` (entities, rules) ← `app` (usecases, ports) ← `adapters`
(PostgreSQL, engine, OPA, storage, clients) ← `api` (routers, wiring). A test of an inner layer needs no database or
network. Designed: `agents-service` still has `ops_agents.api`, `ops_agents.graphs` and `ops_agents.activities`, and
`scripts/check_standards.py` enforces their order.

## Packages

| Rule | Detail |
|---|---|
| What goes in a package | Code with no one service's business rules, used by two or more services or by another project |
| Direction | Services import packages; packages never import a service and receive what they need as arguments or run config |
| Tables | A package that needs tables (the checkpointer) ships its schema as a migration the using service applies |
| Naming | Named for what the library does; no `shared`, `common`, `utils` or `helpers` |
| Env | Only `ops_service_kit` settings reads env |

| Package | What it does | Used by | State |
|---|---|---|---|
| `contracts` (`ops_contracts`) | API models, hand-written; generation from OpenAPI is designed | agents, console | Built |
| `ops_service_kit` | Settings, errors, ids, logging | every service | Built; envelope, auth and embedding (`OPS_ENABLED_SERVICES`) are designed |
| `ops_agent_kernel` | One agent turn, with its token usage (spec 15) | agents | Built |
| `ops_checkpointer` | LangGraph checkpointer on SQLAlchemy Core, on PostgreSQL and SQL Server, with tenant and team isolation | agents | Built |
| `ops_metering` | Usage, prices, cost, totals and budget checks; no I/O | agents; models-service later | Built (E12) |
| `ops_policy` | RFC 8785 input hash, approval-token signing and verification, step-up tokens | agents, tools | Built; the OPA client stays in tools-service |
| `ops_storage` | Object storage protocol: filesystem, S3, Azure Blob (ADR-0010) | files | Built |
| `ops_ingest` | Parsing, splitting, metadata, dedupe, source rules | kb | Built |
| `usecase-runner` | Runs `docs/usecases` scripts and reports verdicts | `make usecase-test` | Built |
| `ops_engine` | The workflow runner: node type registry, compiler to LangGraph, step journal, Postgres work queue, worker loop, leases with generation fencing, reconcile-by-key ([workflow-runner.md](workflow-runner.md)) | agents | Built in part (slice 1); runs inside agents-service |
| `ops_hitl` | Reviews, Cases, work items, decisions, approval-token minting | agents | Planned; the code lives in `agents-service` today |
| `ops_triggers` | Schedule, webhook, email and poll triggers that start agent runs and workflow runs | agents | Planned |
| `sdk-ts`, `sdk-py` | Generated clients | console, services | Designed |

## Deployment targets

Every release must run on one virtual machine with no container runtime; Compose and Kubernetes are optional.

| Target | Shape | State |
|---|---|---|
| `deploy/compose/` | `app.yaml`: one image per service plus the worker, console, OPA and a proxy, a one-shot migrate job, PostgreSQL outside (`docs/deploy/compose.md`); `compose.yaml`: PostgreSQL and OPA for local development | Built |
| `deploy/vm/` | systemd units, each one copy of `ops-host` with a set of services: one with most services, one with `tools-service`, one with `models-service`; native PostgreSQL; OPA binary; local file storage | Designed |
| `deploy/k8s/` | Kustomize base per service, overlays per environment, the migrate Job, per-service Secrets, an outside PostgreSQL (`docs/deploy/kubernetes.md`) | Built; proven on kind |

Every service therefore runs embedded with nothing beyond its database, uses one database server, and has no
container-only dependency. The engine is `ops_engine` with LangGraph as the runner on PostgreSQL. PostgreSQL runs today;
SQL Server 2025 and Azure SQL are being added ([ADR-0017](decisions/database-support.md)).

## Steps left

| Step | What changes |
|---|---|
| Onion layout in `agents-service` | Regroup `api`, `graphs`, `activities` into `domain`, `app`, `adapters`, `api` |
| Tools service stands alone | `ops_tools` stops importing the seed catalogue and local executors from `ops_agents.activities` (`registry.py`, `tools.py`, `__main__.py`); then `tests/gateway` moves to `services/tools-service/tests`, which needs agents fixtures until then |
| `ops_hitl` | Move the Reviews facade, decisions and token minting out of `agents-service` into the package |
| `ops_triggers` | Build the package |
| `ops-host` | One host that starts any set of services in one process |
| Migrations per service | Done for tools: own chain (`alembic_version_tools`) adopting `gateway_calls` and `gateway_fences`; agents 0006 and 0008 still create them on a fresh database. Left: review tables, with `ops_hitl` |
| `ops_service_kit` contents | Envelope, auth and wiring move in; the seed directory default stops pointing into agents tests |
| `ops_engine` | Finish the runner slices after an earlier change |
| models-service | Per-key ledger behind the key-admission port, on `ops_metering` |
| `deploy/vm`, `deploy/k8s` | Build the targets |

## Open questions

1. Which operating systems must `deploy/vm/` support first?
