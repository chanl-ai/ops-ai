# Documentation

Status: current. Every document below is a draft for review unless its own status line says otherwise.

These documents design an operational AI platform for banks and describe the console in
`apps/console/` that shows it. No backend code exists yet.

## Reading order

| Reader | Read in this order |
|---|---|
| Engineer | `background/problem-statement.md` → `architecture/overview.md` → `backend/overview.md` → the topic spec for the area you work on → `specs/design-lessons.md` → `plan/implementation-plan.md` |
| Architect | `background/problem-statement.md` → `architecture/overview.md` → `architecture/decisions/` (ADR-0001 to ADR-0010) → `specs/03-data-and-ai-gateways.md` → `backend/overview.md` |
| Risk reviewer | `background/problem-statement.md` → `architecture/overview.md` (traceability, failure modes) → `specs/04-evals-and-release.md` → `specs/08-model-risk.md` → `specs/09-governance-and-admin.md` → ADR-0005 |

## Requirements

| # | Requirement | Where it is met |
|---|---|---|
| 1 | Implement the problem statement: seven reasons, three decisions and the model-traffic mandate, four components, edit classes, ten knowledge requirements | Every spec; traceability in `architecture/overview.md` |
| 2 | Deliver the email-to-workflow reference flow: mailbox, understand, route to case, queue and SLA, drafted actions with per-action approval | `specs/01-agent-builder.md`, `specs/03-data-and-ai-gateways.md` |
| 3 | Fix the architecture first, with each decision stating options, criteria, evidence and what would change it | `architecture/decisions/` |
| 4 | Build on open source (Temporal and peers) so existing implementations can plug in | ADR-0001, ADR-0007 |
| 5 | Choose the implementation language on the merits | ADR-0002 |
| 6 | Keep workflows and agents portable to other platforms; assess the Agent Workflow Protocol (AWP) and adjacent standards | ADR-0003 |
| 7 | One spec per topic | `specs/` |
| 8 | Apply lessons from earlier agent platforms; the agents are internal and not voice or customer facing | `specs/design-lessons.md`, cited in each spec |
| 9 | Treat the console as the UI reference; each spec states what each screen needs from the backend | "UI mapping" section of each spec |
| 10 | The bank runs no workflow or agent runtime today, so the runtime choice is greenfield; existing agents stay behind adapters | ADR-0001 |
| 11 | Judge every decision on the marginal effort of the next workflow, not only the first | `architecture/overview.md` (throughput), each spec's "Marginal effort" section |
| 12 | Staff chat with agents inside the platform, with MCP Apps for in-chat data views | `specs/07-agent-chat.md`, ADR-0009 |
| 13 | First workflow: the lending servicing inbox (hardship, payoff statements, address changes), with no money movement, so it fits the `low` and `medium` tiers | `plan/implementation-plan.md` |

## Index

| Path | Topic |
|---|---|
| `background/problem-statement.md` | Why bank AI workflows stall, what the platform needs, the reference flow. Item IDs every spec traces to |
| `architecture/overview.md` | Reference architecture, layering, evaluation criteria, throughput, end-to-end flow, traceability, failure modes, open questions |
| `architecture/decisions/ADR-0001-durable-execution-runtime.md` | Temporal and the graph interpreter |
| `architecture/decisions/ADR-0002-implementation-language.md` | Python for execution and the control plane, TypeScript for the UI |
| `architecture/decisions/ADR-0003-workflow-definition-format.md` | Declarative definition format, templates, portability |
| `architecture/decisions/ADR-0004-deployment-tenancy-and-promotion.md` | Environments, worker pools, egress, promotion by pointer, gate tiers |
| `architecture/decisions/ADR-0005-identity-and-entitlement.md` | Workflow identities, delegation, approvals and approval tokens |
| `architecture/decisions/ADR-0006-data-stores-and-evidence.md` | PostgreSQL, WORM object store, pgvector |
| `architecture/decisions/ADR-0007-build-vs-adopt.md` | What is adopted and what is built |
| `architecture/decisions/ADR-0008-ai-gateway.md` | Portkey behind a key-and-budget service |
| `architecture/decisions/ADR-0009-chat-experience.md` | In-console chat and MCP Apps |
| `architecture/decisions/ADR-0010-object-storage.md` | Storage adapter with Amazon S3 and Azure Blob Storage as first-class backends |
| `specs/01-agent-builder.md` | Registry, workflows, agents, versions, edit classes, human steps, cases, queues, SLAs |
| `specs/02-knowledge.md` | Knowledge sources, metadata, scope, precedence, freshness, citations, curation |
| `specs/03-data-and-ai-gateways.md` | Tool modules, approvals, credentials, call logs, mailbox intake, AI gateway |
| `specs/04-evals-and-release.md` | Suites, baselines, agent evals, evidence, gate by risk tier, promotion |
| `specs/07-agent-chat.md` | Chat with agents inside the platform |
| `specs/08-model-risk.md` | Model inventory, tiering, validation, monitoring |
| `specs/09-governance-and-admin.md` | Teams, roles, audit, access, notifications, webhooks, API keys, usage, search |
| `specs/10-files.md` | Files API: presigned uploads, scanning, dedupe, references, retention, legal hold, WORM evidence, storage settings |
| `specs/design-lessons.md` | Engineering lessons from earlier agent and tool platforms |
| `plan/implementation-plan.md` | Phases, teams, workstreams, stop condition |
| `backend/overview.md` | Service map, repo layout, contract flow, standards, security boundaries |
| `ui/page-plan.md` | Console pages and the rules every page follows |
| `ui/tools-design.md` | Design of the tool module screens |

Spec numbers 05 and 06 are not used: the plan and the lessons moved out of `specs/`, and the
remaining numbers stay so that cross-references such as "`03` 5.2" are stable.
