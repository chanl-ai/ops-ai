# Backend overview

Status: draft for review. No backend code exists yet. This document describes the services, repo
layout, contracts and standards the backend will follow, so that work can start from one agreed
shape. The console in `apps/console/` runs against an in-memory mock until these services exist.

Binding decisions are in `docs/architecture/decisions/` (ADR-0001 to ADR-0009). Behaviour is
specified in `docs/specs/`. Timing comes from `docs/plan/implementation-plan.md`.

## 1. Service map

| Service | Folder | What it owns | Data stores | Spec |
|---|---|---|---|---|
| Control-plane API | `services/control-plane/` | Registry (workflows, agents, versions, risk tier, owner, cost, release pointers), drafts and edit classes, publish requests and the release gate, cases, queues and SLAs, reviews, governance (teams, roles, audit, notifications, API keys, usage). Serves the OpenAPI contract the console calls | PostgreSQL (system of record), WORM object store (evidence bundles, audit export) | `01` 4–6, `04` 4.5–4.7 and 5.5–5.7, `08`, `09`; ADR-0004, ADR-0006 |
| Workflow interpreter | `services/interpreter/` | One Temporal workflow type that walks any compiled execution plan, the node-type implementations, activity workers per risk tier, the agent-block host | Temporal history (owned by Temporal); writes run journal rows and payloads through the control plane and object store | `01` 4.6, 5.6, 5.7; ADR-0001, ADR-0003 |
| Data gateway | `services/data-gateway/` | Tool and knowledge modules, module versions and approvals with expiry, the per-call policy decision (OPA), credential resolution from the secret store, subject binding, approval-token checks on writes, the call log | PostgreSQL (modules, approvals, call log), secret store (credentials), pgvector database (read path for knowledge) | `03` 4.1–4.5, 5.1–5.5; ADR-0005 |
| Key-and-budget service (AI gateway front) | `services/ai-gateway/` | Model aliases, per-workflow and per-purpose keys and budgets, metadata logging, failover rules, agent discovery from traffic. Holds every model key; Portkey's open-source gateway runs behind it as the data plane | PostgreSQL (aliases, budgets, usage), secret store (provider keys) | `03` 4.8, 5.8–5.10; ADR-0008 |
| Mailbox intake | `services/mailbox-intake/` | Shared-mailbox polling (Microsoft Graph delta every 60 s per folder), security scan, archive, the new-mail event that starts a run, daily reconciliation | PostgreSQL (mailbox state, intake records), WORM object store (mail archive, attachments) | `03` 4.6, 5.6; ADR-0007 |
| Knowledge ingestion | `services/knowledge-ingest/` | Source sync, required-metadata checks, chunking, embedding through the AI gateway under the ingestion identity, indexing, freshness and staleness, the citation index | pgvector database (separate PostgreSQL instance), object store (source copies) | `02` 4, 5.1–5.8, 5.13; ADR-0006 |
| Eval runner | `services/eval-runner/` | Suite runs on publish requests, agent evals, model-update runs, scoring against baselines, injection thresholds, sealing evidence bundles | PostgreSQL (runs, results, baselines), WORM object store (evidence bundles) | `04` 4.1–4.6, 5.1–5.4, 5.8–5.10 |
| Shared libraries | `services/shared/` | Generated models from `packages/contracts`, settings loading, logging and tracing setup, run-context and identity types, gateway clients | none | Section 3 below |

All services are Python (ADR-0002). The console's backend-for-frontend stays in TypeScript inside
`apps/console/`.

## 2. Layout

```text
services/
  control-plane/        FastAPI app: registry, gate, cases, governance
  interpreter/
    nodes/              one module per node type (classify_intent, extract_fields, open_case, ...)
    agent_host/         wrapper that runs existing Python agents as agent blocks
  data-gateway/
    modules/            adapters per tool-module kind (MCP, OpenAPI, native)
    policy/             OPA policies and their tests
  ai-gateway/           key-and-budget service; Portkey configuration generated from the registry
  mailbox-intake/
  knowledge-ingest/
  eval-runner/
  shared/               generated contract models, settings, logging, tracing, clients
packages/
  contracts/            OpenAPI 3.1 and JSON Schema, generated TS and Python types
deploy/
  compose/              local development stack (planned)
```

| Thing | Lives in | Notes |
|---|---|---|
| Node types | `services/interpreter/nodes/` | Each node type has a JSON Schema for its settings in `packages/contracts`; the interpreter refuses a plan whose node settings fail validation |
| Tool modules | Published as data (module definitions and versions) in the data gateway's store; adapter code per module kind in `services/data-gateway/modules/` | A new tool module for an existing kind (MCP, OpenAPI) is configuration, with no code change |
| Knowledge modules | Served by the data gateway; built by `services/knowledge-ingest/` | Same approval model as tool modules |
| Agent blocks | Packaged agent code run by `services/interpreter/agent_host/` | Every model call goes through the AI gateway |

## 3. Contract flow

The console's TypeScript contract (`apps/console/src/lib/api/*-contract.ts` and
`apps/console/src/lib/types/`) is the starting point, because the screens already exercise it.

```mermaid
flowchart LR
  TS["Console contract<br/>apps/console/src/lib/api/*-contract.ts"] --> OAS["packages/contracts<br/>OpenAPI 3.1 + JSON Schema"]
  OAS --> PY["Generated Python models<br/>services/shared"]
  OAS --> TT["Generated TypeScript types<br/>apps/console"]
  PY --> SVC["Control-plane handlers"]
  TT --> HTTP["apps/console/src/lib/api/*-http.ts"]
  CI["CI equality check"] -.-> OAS
  CI -.-> PY
  CI -.-> TT
```

| Step | What happens |
|---|---|
| 1 | The contract is moved into `packages/contracts` as OpenAPI 3.1 (operations) and JSON Schema (domain types and workflow definitions) |
| 2 | Python models for the services and TypeScript types for the console are generated from it and committed |
| 3 | CI regenerates both and fails if either differs from what is committed, so a hand-edited generated type fails the build |
| 4 | The control plane serves the OpenAPI operations with the `{ success, data }` envelope the HTTP client expects |
| 5 | The console switches from mock to HTTP when `NEXT_PUBLIC_OPS_API_URL` is set (`apps/console/src/lib/api/index.ts:8`). No other console file changes |

## 4. One run end to end

The phase-1 email workflow, from arrival to audit. Module names in the last column are the planned
Python packages.

```mermaid
sequenceDiagram
  autonumber
  participant MB as Shared mailbox
  participant MI as mailbox-intake
  participant CP as control-plane
  participant T as Temporal
  participant I as interpreter
  participant AI as ai-gateway (+ Portkey)
  participant DG as data-gateway
  participant P as Approver (console)
  participant A as Audit log / object store

  MI->>MB: Graph delta poll (60 s)
  MI->>A: Archive mail and attachments
  MI->>CP: New-mail event (intake record)
  CP->>T: Start run at the live release pointer
  T->>I: Execute plan
  I->>AI: classify_intent, extract_fields (workflow key)
  I->>DG: Read tools and knowledge (scoped, logged)
  I->>CP: open_case: case, queue, SLA timer
  I->>AI: draft_action (drafting agent)
  I->>CP: Store drafted actions with citations
  CP->>P: Decision task per action
  P->>CP: Approve action
  CP->>T: Update with approval token bound to the action payload
  T->>I: Resume
  I->>DG: Write call with approval token
  DG->>DG: Check token matches payload, scope, expiry, entitlement
  DG->>A: Call log row joined by run id
  I->>CP: Run journal, case update
  CP->>A: Audit event
```

| Step | Service | Planned module |
|---|---|---|
| Mail polled, scanned, archived | mailbox-intake | `mailbox_intake.graph_delta`, `mailbox_intake.scan`, `mailbox_intake.archive` |
| Run started at the live pointer | control-plane | `control_plane.registry.pointers`, `control_plane.runs` |
| Classify and extract | interpreter, ai-gateway | `interpreter.nodes.classify_intent`, `interpreter.nodes.extract_fields` |
| Case opened, routed, SLA started | interpreter, control-plane | `interpreter.nodes.open_case`, `control_plane.cases` |
| Actions drafted | interpreter, ai-gateway, data-gateway | `interpreter.nodes.draft_action`, `interpreter.agent_host` |
| Approval token issued | control-plane | `control_plane.approvals.tokens` |
| Approved write executed | interpreter, data-gateway | `interpreter.nodes.per_action_approval`, `data_gateway.calls`, `data_gateway.policy` |
| Audit and evidence | all, via control-plane and object store | `control_plane.audit`, `shared.logging` |

## 5. Local development (planned)

One compose file at `deploy/compose/compose.yaml` will start the dependencies; the services run on
the host with hot reload. None of this exists yet.

| Container | Purpose |
|---|---|
| Temporal (with its own PostgreSQL) | Durable execution |
| PostgreSQL `ops` | System of record |
| PostgreSQL `knowledge` with pgvector | Knowledge index, separate database as in ADR-0006 |
| Object store (S3-compatible) | Mail archive, payloads, evidence bundles |
| Portkey gateway | AI gateway data plane |
| OPA | Policy decisions for the data gateway |

Planned commands:

```bash
docker compose -f deploy/compose/compose.yaml up -d
uv sync
uv run --package control-plane uvicorn control_plane.app:app --reload
uv run --package interpreter python -m interpreter.worker
```

## 6. Standards

| Area | Standard |
|---|---|
| Language and tooling | Python 3.12, uv workspaces, ruff (lint and format), pyright (strict on `shared` and gateway code), pytest |
| Tests | Unit tests for pure logic; integration tests against the compose stack for each service's store and gateway calls; end-to-end tests that drive a real email through intake to an audited write in `test`. One test per failure mode, each seen failing once before it is trusted. No tests that only exercise a third-party library |
| Config | Settings loaded once into a validated settings object at start-up; a missing or malformed value stops the service at boot. No `.env` files in the repo; secrets come from the secret store |
| Logs and traces | Structured JSON logs with run id, workflow id, version and subject on every line; OpenTelemetry traces across services, with the run id as a span attribute |
| API | OpenAPI 3.1 from `packages/contracts`; `{ success, data }` envelope; idempotency keys on writes |
| Data access | Each service owns its tables; no service reads another service's tables |

## 7. Security boundaries

| Boundary | Rule |
|---|---|
| Trust facts | Identity, team, subject and tier come from platform context (run context, tokens). Message text, email bodies and model output never set them |
| Keys | Workers and agent blocks hold no model keys and no system credentials. The key-and-budget service holds model keys; the data gateway resolves system credentials from the secret store |
| Egress | Worker pods reach only Temporal, the two gateways and the object store. Every model call goes through the AI gateway and every system call through the data gateway |
| Writes | A write needs an approval token bound to the exact action payload; the data gateway rejects a token whose payload digest differs |
| Records | The model does not choose which record a write touches; the subject binding comes from the case |
| Fail closed | Each control declares whether it fails open or closed; approval, scope and egress checks fail closed |

## 8. Walking skeleton versus phase 1 production

| Capability | Walking skeleton (week 8, `test` only) | Phase 1 production (week 20, pilot to week 24) |
|---|---|---|
| Intake | One test mailbox polled every 60 s | The first real shared inbox, with scan, archive and daily reconciliation |
| Interpreter | Plan with the email-intake node types, one worker pool | Pools for `low` and `medium`, pinned worker versions |
| AI gateway | Portkey behind a first cut of the key-and-budget service, one alias | Aliases, per-workflow and per-purpose keys and budgets, metadata logging, egress lock |
| Data gateway | OPA with one allow and one deny rule, stubbed send | Approvals with expiry, credential resolution, call log, approval-token checks on writes |
| Cases | Case, queue and SLA timer created | Queues, SLAs, calendars, approval rules and the review workbench |
| Knowledge | none | One knowledge base with metadata checks, citations and a golden set |
| Evals | none | Suite in the gate, injection threshold, evidence bundles sealed per version |
| Release | `test` pointer table | Production pointer, four-eyes publish, rollback by pointer |
| Contracts | Generated OpenAPI, JSON Schema and types with the CI equality check | Same, covering every phase-1 operation |

## Open questions

| # | Question |
|---|---|
| 1 | Whether the control plane is one deployable or splits cases and governance into their own services once load is known |
| 2 | Which S3-compatible store with object lock the bank runs on-premises, and whether the local stack can use the same product |
| 3 | Whether the contract moves to `packages/contracts` by generation from the TypeScript types or by hand-writing OpenAPI first and generating the console types from it |
