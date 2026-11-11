# Platform choices

Status: current, 2026-11-11. Code cited at commit 81c9883a. This page states the product and library each part of
Ops AI is built on today, with where it lives in code and the page that describes it. It holds the current outcome of
every record in [decisions/](decisions/); those records keep the options and scoring that led there.

## Choices by area

| Area | Current choice | Built | Where | Described in |
|---|---|---|---|---|
| Implementation language | Python for every service and package; TypeScript for the console and the embed app | Yes | `services/`, `packages/`, `apps/console`, `apps/embed` | [service map](service-map.md) |
| Workflow and agent execution | One engine, `ops_engine`, compiling definitions to LangGraph graphs run on PostgreSQL; no Temporal | Yes | `packages/ops_engine/src/ops_engine/compiler.py`, `packages/ops_engine/src/ops_engine/worker.py` | [runtime](runtime.md), [workflow runner](workflow-runner.md) |
| Checkpoints | Own asyncpg checkpointer, row-level security per tenant | Yes | `packages/ops_checkpointer/src/ops_checkpointer/saver.py` | [durability, failure and audit](durability-failure-and-audit.md) |
| Fencing | A thread is fenced by its lease generation: a stale owner's checkpoint, journal, status, timer and tool writes are refused | Yes | `packages/ops_engine/src/ops_engine/journal.py:32` | [durability, failure and audit](durability-failure-and-audit.md) |
| Timers | A `timers` table and a poller in PostgreSQL, fired through agents-service's timers route | Yes | `services/agents-service/src/ops_agents/api/routers/timers.py` | [human in the loop](human-in-the-loop.md) |
| Agent loop | Pydantic AI in Python; the AI SDK (`ai` 7) for chat message parts in the console | Yes | `services/agents-service/src/ops_agents/api/routers/chat.py:22`; `apps/console/package.json:47` | [runtime](runtime.md), [agent guardrails](agent-guardrails.md) |
| AI gateway | models-service holds provider keys per account, model aliases and budgets; it calls any OpenAI-compatible base (a provider, a local model server or an outside gateway) | Yes | `services/models-service/src/ops_models/connection_settings.py:5` | [service map](service-map.md) |
| Data gateway | tools-service runs every tool call, holds the credentials, checks policy and logs the call | Yes | `services/tools-service/src/ops_tools/gateway_calls.py` | [tool lifecycle](tool-lifecycle.md) |
| Write approval | A write runs only with an approval bound to a hash of its input; a money operation can need two approvers | Yes | `services/tools-service/src/ops_tools/app.py:20,515` | [human in the loop](human-in-the-loop.md), [roles and permissions](roles-and-permissions.md#approvals) |
| Identity of runs | A run acts for a person through a delegation, or as a process principal; its entitlement is the intersection of the tool's scopes and the principal's | Yes | `packages/ops_identity/src/ops_identity/acting_for.py` | [identity and tenancy](identity-and-tenancy.md) |
| Human sign-in | One provider seam in the console with `platform`, `oidc`, `firebase` and `unconfigured` adapters; the sign-in library holds password, OIDC and SAML | Yes | `apps/console/src/lib/auth/providers/`; `packages/ops_signin/src/ops_signin/` | [identity and tenancy](identity-and-tenancy.md), [SAML sign-in](saml-sign-in.md) |
| Database | PostgreSQL and SQL Server through one dialect layer; SQLite for unit tests only; any other dialect is refused | Yes | `packages/ops_store/src/ops_store/dialect.py:30` | [data](data.md), [data model](data-model.md), [SQL Server](../design/data/sql-server.md) |
| Object storage | One storage adapter with local, Amazon S3 and Azure Blob Storage backends | Yes | `packages/ops_storage/src/ops_storage/s3.py`, `azure_blob.py`, `local.py` | [files-service](../services/files-service/overview.md) |
| Shared prompt text | An always-on skill pinned by version; instructions live on the agent version; no prompt registry | Yes | `services/agents-service/src/ops_agents/api/routers/skills.py` | [agent guardrails](agent-guardrails.md) |
| Definitions | Declarative definitions stored as records, drafted, reviewed and published by pointer; a thread pins the version it started on | Yes | `packages/ops_engine/src/ops_engine/definition.py` | [definitions and versions](definitions-and-versions.md) |
| Assurance | Every asset (workflow, agent, skill, tool module) follows one draft, review and publish lifecycle through one Reviews queue | Yes | `services/agents-service/src/ops_agents/api/routers/reviews.py`, `publish_requests.py` | [definitions and versions](definitions-and-versions.md), [human in the loop](human-in-the-loop.md) |
| Chat | In-console chat on agents-service's agent run API; record cards and widgets in the conversation | Yes | `services/agents-service/src/ops_agents/api/routers/chat.py`; `apps/console/src/components/chat/` | [chat widgets](chat-widgets.md), [embedded chat](embedded-chat.md) |
| Deployment | Services run as `ops-host` processes on a VM, Compose or Kubernetes; promotion moves a version pointer | Yes | `deploy/host`, `deploy/compose`, `deploy/k8s` | [service map](service-map.md), [operations](operations.md) |
| Logging | structlog JSON lines on stdout with ids and redaction | Yes | `packages/ops_service_kit/src/ops_service_kit/logging.py` | [logging and data writes](logging-and-data-writes.md) |

## Rules that follow from these choices

| Rule | Consequence |
|---|---|
| Every model call goes through models-service | A service never holds a provider key; a call that names no account is refused (rule D65 in [roles and permissions](roles-and-permissions.md#access-rules)) |
| Every tool call goes through tools-service | Agents and workflows never call an outside system directly; credentials never leave the gateway |
| Every change a store makes runs on PostgreSQL and SQL Server | `scripts/check_portable_store.py` holds the known findings in a baseline that may only fall ([data](data.md)) |
| A new dependency is listed with its licence and network behaviour | [dependencies](dependencies.md), generated by `make sbom` and checked by `make verify` |
