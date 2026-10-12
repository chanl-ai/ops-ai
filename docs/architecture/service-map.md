# Service map

Status: current. Approved by the owner; where a row says designed, it is the target and is not built yet. Specs 14
and 17 defer to this page where they differ.

## Services

Each service is named after the console section it serves. `packages/` holds reusable libraries; `services/` holds
deployables.

| Service | Console section | Owns | State |
|---|---|---|---|
| `platform-service` | Govern: Access, Audit log, Settings | Sign-in, sessions, tenancy, teams, roles, audit, API keys; later notifications, usage, search. The only issuer of identity tokens (asymmetric, public keys at a JWKS route); every service verifies locally through `ops_identity`. Routes nothing and hosts nothing; holds no model or tool credentials | In code: `services/platform-service`, `packages/ops_identity` (`docs/services/platform-service/overview.md`); adoption by agents and tools next |
| `agents-service` | Agents, Workflows, Deployments, Skills; Chat; Assurance | Definitions and versions, publish and release gate, evals, channels (mailbox, widget, MCP, API), execution: kernel turns, threads, runs, leases, timers, usage and thread budgets | Prototype in `services/agents-service` |
| `hitl-service` | Work: Cases, Reviews | Cases, queues, SLA display, Reviews, decisions, approval tokens issued to people (ADR-0005) | Designed; the Reviews facade and decisions live in `agents-service` today |
| `tools-service` | Data Hub: Tools, Connections; tool-call Activity | Tool egress: tool modules, credentials, OPA policy, approval-token checks, call log and dedupe | Prototype in `services/tools-service` |
| `models-service` | AI gateway (`docs/plan/ai-gateway-console.md`) | Model egress: aliases, provider keys, per-key ledgers and budgets, logging, failover, in front of Portkey (ADR-0008) | Designed; agents-service asks a key-admission port that admits every key |
| `kb-service` | Data Hub: Knowledge bases, Wiki | Sources, ingestion, indexing, retrieval, citations, freshness | Designed; library in `packages/ops_ingest` |
| `files-service` | Data Hub: Documents, uploads | File bytes: upload, download, scanning, dedupe, retention, legal hold, WORM evidence | Service logic with tests in `services/files-service`, no server |

Tool calls and model calls go through different services: a tool call acts on a bank system and needs an approval
token per call; a model call spends budget and needs a key per identity. Channels start runs, so they belong to
`agents-service`.

## Naming

One short name runs through every layer, so a service can move to its own repository without renames.

| Layer | Pattern | Example |
|---|---|---|
| Folder and repository | `services/<x>-service` | `services/agents-service` |
| Python distribution | `ops-<x>-service` | `ops-agents-service` |
| Python module | `ops_<x>` | `ops_agents` |
| Docs | `docs/services/<x>-service/` | `docs/services/agents-service/` |
| Image, Kubernetes base, systemd unit | `<x>-service` | `agents-service` |

Short names: `platform`, `agents`, `hitl`, `tools`, `models`, `kb`, `files`. Console labels keep their product names.
Settings read the `OPS_` prefix from one shared class; per-service prefixes (`OPS_<X>_`) need per-service settings
classes (designed).

## Specs per service

| Service | Specs and decisions |
|---|---|
| `platform-service` | `docs/specs/governance-and-admin.md`; `docs/specs/sign-in-and-sessions.md`; ADR-0004, ADR-0013 |
| `agents-service` | `docs/specs/agent-builder.md`; `docs/specs/evals-and-release.md`; `docs/specs/agent-chat.md`; `docs/specs/model-risk.md`; `docs/specs/skills.md`; `docs/specs/prompts.md`; specs 14–17; `docs/specs/data-and-ai-gateways.md` 4.6, 5.6 (mailbox); ADR-0001, ADR-0003, ADR-0014, ADR-0015, ADR-0016 |
| `hitl-service` | `docs/specs/agent-builder.md` (cases, queues, SLAs); `docs/specs/evals-and-release.md` (Reviews); ADR-0005, ADR-0012 |
| `tools-service` | `docs/specs/data-and-ai-gateways.md` 4.1–4.5, 5.1–5.5; ADR-0005 |
| `models-service` | `docs/specs/data-and-ai-gateways.md` 4.8, 5.8–5.10; ADR-0008 |
| `kb-service` | `docs/specs/knowledge.md`; ADR-0006 |
| `files-service` | `docs/specs/files.md`; ADR-0006, ADR-0010 |

## Decisions

| Decision | Detail |
|---|---|
| Definitions and execution in one service | Agents, workflows and their runs are one context in the console. Run load is handled by a `worker` process type that scales apart from `api` (designed) |
| Chat lives in `agents-service` | Chat sessions, threads and messages belong to `agents-service`; replaces the default in spec 14 Q2 |
| Definitions are pinned per thread | Immutable versioned JSON definitions with a digest (ADR-0003); each thread compiles and pins `(definition, version, digest)`, so the pin survives a republish |
| Human in the loop is its own context | It scales with reviewers and holds the token signing key, so it keeps its boundary even when embedded |

## Contracts that cross services

| Contract | Rule |
|---|---|
| SLA timers | The step's timeout outcome is pinned in the plan (spec 16, ADR-0005). The agents worker owns the timers table, poller and resume and decides from the pinned plan; hitl-service learns the outcome afterwards to notify and record it |
| Decide then resume | hitl-service records the decision and mints the token, then resumes the thread with the decision id as idempotency key; a failed resume is retried with the same id and resumes once |
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
| `ops_checkpointer` | LangGraph checkpointer on asyncpg with tenant row-level security | agents | Built |
| `ops_metering` | Usage, prices, cost, totals and budget checks; no I/O | agents; models-service later | Built (E12) |
| `ops_policy` | RFC 8785 input hash, approval-token signing and verification, step-up tokens | agents, tools | Built; the OPA client stays in tools-service |
| `ops_storage` | Object storage protocol: filesystem, S3, Azure Blob (ADR-0010) | files | Built |
| `ops_ingest` | Parsing, splitting, metadata, dedupe, source rules | kb | Built |
| `usecase-runner` | Runs `docs/usecases` scripts and reports verdicts | `make usecase-test` | Built |
| `ops_engine` | `Engine` seam (ADR-0015) with the LangGraph adapter, leases, sweeper and timers | agents | Designed; the E9 conformance suite runs on the adapter in `agents-service` |
| `sdk-ts`, `sdk-py` | Generated clients | console, services | Designed |

## Deployment targets

Every release must run on one virtual machine with no container runtime; Compose and Kubernetes are optional.

| Target | Shape | State |
|---|---|---|
| `deploy/compose/` | PostgreSQL and OPA for local development | Built |
| `deploy/vm/` | systemd units: gateway with other services embedded, `tools-service`, `models-service`; native PostgreSQL; OPA binary; local file storage | Designed |
| `deploy/k8s/` | Kustomize base per service, overlays per environment | Designed |

Every service therefore runs embedded with nothing beyond PostgreSQL, uses one PostgreSQL server, and has no
container-only dependency. The default engine, LangGraph on PostgreSQL, meets that; Temporal is an add-on (ADR-0015).

## Steps left

| Step | What changes |
|---|---|
| Onion layout in `agents-service` | Regroup `api`, `graphs`, `activities` into `domain`, `app`, `adapters`, `api` |
| Tools service stands alone | `ops_tools` stops importing the seed catalogue and local executors from `ops_agents.activities` (`registry.py`, `tools.py`, `__main__.py`); then `tests/gateway` moves to `services/tools-service/tests`, which needs agents fixtures until then |
| hitl-service | Move the Reviews facade, decisions and token minting out of `agents-service` |
| Migrations per service | Done for tools: own chain (`alembic_version_tools`) adopting `gateway_calls` and `gateway_fences`; agents 0006 and 0008 still create them on a fresh database. Left: review tables, with hitl-service |
| `ops_service_kit` contents | Envelope, auth and wiring move in; the seed directory default stops pointing into agents tests |
| `ops_engine` | Build the `Engine` seam and move leases, sweeper and timers behind it |
| models-service | Per-key ledger behind the key-admission port, on `ops_metering` |
| `deploy/vm`, `deploy/k8s` | Build the targets |

## Open questions

1. Which operating systems must `deploy/vm/` support first?
