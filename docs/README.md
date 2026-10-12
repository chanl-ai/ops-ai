# Documentation

Status: current. Every document below is a draft for review unless its own status line says otherwise.

These documents design an operational AI platform for banks and describe the console in
`apps/console/` that shows it. Backend code runs for four of the seven services (`services/platform-service`, `services/agents-service`, `services/tools-service`, `services/models-service`); `files-service` is a skeleton and `hitl-service` and `kb-service` are stubs. `architecture/README.md` is the entry page for the system as built.

## Reading order

| Reader | Read in this order |
|---|---|
| Engineer | `background/problem-statement.md` → `architecture/overview.md` → `architecture/service-map.md` → the topic spec for the area you work on → `specs/design-lessons.md` → `plan/implementation-plan.md` |
| Architect | `background/problem-statement.md` → `architecture/overview.md` → `architecture/decisions/` (ADR-0001 to ADR-0016; every ADR is an option, not decided, until the owner confirms it) → `specs/data-and-ai-gateways.md` → `architecture/service-map.md` |
| Risk reviewer | `background/problem-statement.md` → `architecture/overview.md` (traceability, failure modes) → `specs/evals-and-release.md` → `specs/model-risk.md` → `specs/governance-and-admin.md` → ADR-0005 |

## Requirements

| # | Requirement | Where it is met |
|---|---|---|
| 1 | Implement the problem statement: seven reasons, three decisions and the model-traffic mandate, four components, edit classes, ten knowledge requirements | Every spec; traceability in `architecture/overview.md` |
| 2 | Deliver the email-to-workflow reference flow: mailbox, understand, route to case, queue and SLA, drafted actions with per-action approval | `specs/agent-builder.md`, `specs/data-and-ai-gateways.md` |
| 3 | Fix the architecture first, with each decision stating options, criteria, evidence and what would change it | `architecture/decisions/` |
| 4 | Build on open source (Temporal and peers) so existing implementations can plug in | ADR-0001, ADR-0007 |
| 5 | Choose the implementation language on the merits | ADR-0002 |
| 6 | Keep workflows and agents portable to other platforms; assess the Agent Workflow Protocol (AWP) and adjacent standards | ADR-0003 |
| 7 | One spec per topic | `specs/` |
| 8 | Apply lessons from earlier agent platforms; the agents are internal and not voice or customer facing | `specs/design-lessons.md`, cited in each spec |
| 9 | Treat the console as the UI reference; each spec states what each screen needs from the backend | "UI mapping" section of each spec |
| 10 | The bank runs no workflow or agent runtime today, so the runtime choice is greenfield; existing agents stay behind adapters | ADR-0001 |
| 11 | Judge every decision on the marginal effort of the next workflow, not only the first | `architecture/overview.md` (throughput), each spec's "Marginal effort" section |
| 12 | Staff chat with agents inside the platform, with MCP Apps for in-chat data views | `specs/agent-chat.md`, ADR-0009 |
| 13 | First workflow: the lending servicing inbox (hardship, payoff statements, address changes), with no money movement, so it fits the `low` and `medium` tiers | `architecture/service-map.md` | Services, packages, layering, cross-service contracts and deployment targets (VM, Compose, Kubernetes) |

## Architecture

Start at `architecture/README.md`; it gives the reading order and what is proven.

| Path | Topic |
|---|---|
| `architecture/README.md` | Entry page: what Ops AI is, reading order by chapter, what is proven and by which evidence |
| `architecture/overview.md` | The rule, the system picture, seven services, three run kinds, what runs today, evaluation criteria, open questions |
| `architecture/words-and-entities.md` | Glossary (graph, thread, run, interrupt, lease, fence, timer) and the entity relationships |
| `architecture/api.md` | API families and calls, which exist in code, request conventions, the event schema |
| `architecture/runtime.md` | Inside agents-service: kernel, graphs, compiled definitions, the LangGraph adapter, process types, engine seam, libraries |
| `architecture/workflows-as-tools.md` | Workflows as agent tools: an agent starts a published workflow as a child thread and gets its result or a review handle |
| `architecture/human-in-the-loop.md` | Interrupt kinds, review rules, approval tokens, step-up, two approvers, SLA timers, pauses per channel |
| `architecture/channels-and-deployments.md` | Deployments, the adapter contract, identity and keys per channel, busy-thread input, the mailbox adapter |
| `architecture/identity-and-tenancy.md` | Sign-in seam, delegation, process principals, tools gateway, row-level security, prototype shortcuts |
| `architecture/definitions-and-versions.md` | Draft to publish, pointers, the pin per thread, what happens without it, migrate |
| `architecture/durability-failure-and-audit.md` | Leases, sweeper, fencing, re-execution, idempotency, side-effect classes, journal, checkpoint growth and pruning |
| `architecture/data.md` | Tables per service, the checkpointer package, designed stores, retention |
| `architecture/operations.md` | Running it, environments, health, the acceptance gate, what to watch, runbooks |
| `architecture/delivery.md` | What is proven, what is next, known gaps, the open decisions with defaults |

## Index

| Path | Topic |
|---|---|
| `background/problem-statement.md` | Why bank AI workflows stall, what the platform needs, the reference flow. Item IDs every spec traces to |
| `architecture/overview.md` | Reference architecture, layering, evaluation criteria, throughput, end-to-end flow, traceability, failure modes, open questions |
| `architecture/decisions/durable-execution-runtime.md` | Temporal and the graph interpreter |
| `architecture/decisions/implementation-language.md` | Python for execution and the control plane, TypeScript for the UI |
| `architecture/decisions/workflow-definition-format.md` | Declarative definition format, templates, portability |
| `architecture/decisions/deployment-tenancy-and-promotion.md` | Environments, worker pools, egress, promotion by pointer, gate tiers |
| `architecture/decisions/identity-and-entitlement.md` | Workflow identities, delegation, approvals and approval tokens |
| `architecture/decisions/data-stores-and-evidence.md` | PostgreSQL, WORM object store, pgvector |
| `architecture/decisions/build-vs-adopt.md` | What is adopted and what is built |
| `architecture/decisions/ai-gateway.md` | Portkey behind a key-and-budget service |
| `architecture/decisions/chat-experience.md` | In-console chat and MCP Apps |
| `architecture/decisions/object-storage.md` | Storage adapter with Amazon S3 and Azure Blob Storage as first-class backends |
| `architecture/decisions/prompt-management.md` | Superseded 2026-10-08: shared text is an always-on skill (spec 11). Instructions stay on agent versions; no external prompt registry in phase 1 |
| `architecture/decisions/assurance.md` | Governance and testing as one system: one asset lifecycle, one Reviews queue with tier-set approval properties, one eval primitive with calibrated judges, one evidence bundle the model inventory reads |
| `architecture/decisions/auth-provider-seam.md` | Human sign-in: one AuthProvider seam with mock, oidc and firebase adapters; policy from the API |
| `architecture/decisions/agent-loop-library.md` | Agent loop library scored; Pydantic AI for Python, AI SDK for TypeScript |
| `architecture/decisions/execution-engine-seam.md` | Engine seam: Temporal preferred where allowed, LangGraph on PostgreSQL built first, one conformance suite |
| `architecture/decisions/fencing-and-timers.md` | Fencing the thread by lease generation; timers as a port with a fire endpoint; Temporal tests before a Temporal adapter |
| `specs/agent-builder.md` | Registry, workflows, agents, versions, edit classes, human steps, cases, queues, SLAs |
| `specs/knowledge.md` | Knowledge sources, metadata, scope, precedence, freshness, citations, curation |
| `specs/data-and-ai-gateways.md` | Tool modules, approvals, credentials, call logs, mailbox intake, AI gateway |
| `specs/evals-and-release.md` | Assurance: one asset lifecycle, one Reviews queue, datasets with outcome and trace graders, calibrated judges, multi-turn simulation, evidence bundle, gate by risk tier, promotion, the rejection-to-case loop |
| `specs/agent-chat.md` | Chat with agents inside the platform |
| `specs/model-risk.md` | Model inventory, tiering, validation and conditions; quality numbers and evidence read from Assurance records |
| `specs/governance-and-admin.md` | Teams, roles, audit, access, notifications, webhooks, API keys, usage, search |
| `specs/files.md` | Files API: presigned uploads, scanning, dedupe, references, retention, legal hold, WORM evidence, storage settings |
| `specs/skills.md` | Skills: versioned procedures agents load by use-when match, and always-on skills for shared text; tests, maker-checker publish, pins, generation, `SKILL.md` import and export |
| `specs/prompts.md` | 12 Prompts: agent templates, the prompt generator and its lint, variables |
| `specs/sign-in-and-sessions.md` | Human sign-in: AuthProvider seam (mock, oidc, firebase), sign-in policy, SSO by domain, MFA, invites, account security, step-up before money approvals in every channel |
| `specs/platform-service.md` | Platform service first slice: tenants, teams, members, API keys, sessions, audit, the `ops_identity` contract every service uses, isolation rules and the six use cases that gate it |
| `specs/runtime-service.md` | Runtime: the one service that runs workflow runs, agent runs and chat sessions on the Temporal interpreter; its API (R1–R19); dependencies on registry, gateways, identity, cases, audit, files, channels and Assurance, each marked exists in Protobox or must be built |
| `specs/agent-kernel.md` | Agent kernel: one Python package that runs one agent turn for a workflow node or a chat turn; context assembly, loop, interrupts and resume, UI message stream, memory proposals, tracing; Pydantic AI in phase 1 (ADR-0014) |
| `specs/interpreter-and-nodes.md` | Interpreter: one Temporal workflow type walking a compiled plan; node catalogue (15 kinds, mock versus new), human steps as Updates with approval tokens, versioning by plan digest plus Worker Versioning, task queues per tier, failure handling, replay tests, walking skeleton |
| `specs/python-service-skeleton.md` | The Python runtime service: uv workspace and packages (layout superseded by `architecture/service-map.md`), libraries with verified versions, contracts generation, FastAPI Runtime API, Temporal workers, local compose and make targets, verify gate, deployment, how it calls Protobox, one-week walking skeleton |
| `specs/design-lessons.md` | Engineering lessons from earlier agent and tool platforms |
| `plan/implementation-plan.md` | Phases, teams, workstreams, stop condition |
| `console/page-plan.md` | Console pages and the rules every page follows |
| `console/standards.md` | Console UI standard: tokens, layout primitives, compose-from-shadcn, designed states, responsive, one-screen create, and the review checks |
| `console/strategy.md` | Console strategy: thin UI over a generated SDK, per-page audit with verdicts, the agentic core slice, chat on the thread calls, what to stop |
| `console/tools-design.md` | Design of the tool module screens |
| `usecases/README.md` | Use case registry: how to run, rules (scripted model only, PASS needs evidence), layout, exit codes |
| `usecases/agents-service/chat-turn-with-citation.md` | uc-001: chat turn with citation |
| `usecases/agents-service/write-tool-approval-step-up.md` | uc-002: write tool pauses and approval resumes with step-up |
| `usecases/agents-service/simple-workflow.md` | uc-003: simple workflow through the four thread calls |
| `usecases/agents-service/complex-workflow.md` | uc-004: complex workflow with fan-out, grade loop, review pause and send |
| `usecases/agents-service/pause-survives-restart.md` | uc-005: a pause survives a restart |
| `usecases/agents-service/sla-breach-escalates.md` | uc-006: SLA timer breach escalates |
| `usecases/tools-service/write-without-token-refused.md` | uc-007: a tool write without a token is refused |
| `usecases/tools-service/manage-tool-modules.md` | uc-010: a builder creates, versions and approves a tool module, and it survives a restart |
| `usecases/tools-service/calls-through-the-registry.md` | uc-011: a tool call runs through the registry and is logged with its caller |
| `usecases/tools-service/import-tools.md` | uc-012: tools imported from OpenAPI and MCP, called only on hosts and ranges the tenant allows |
| `usecases/tools-service/secrets.md` | uc-013: a tool's credential is a secret, sent at call time and never returned |
| `usecases/tools-service/module-traffic-from-real-calls.md` | uc-042: a module's call counts, error rate, p95 and activity come from the gateway's call log |
| `usecases/tools-service/security-decides-a-module-review.md` | uc-040: only Security's approver decides a module's security review, from Reviews or the module page |
| `usecases/tools-service/tool-module-details-page.md` | uc-015: the tool module details page, test panel beside the tabs and executions with their caller |
| `usecases/agents-service/decide-paused-workflow.md` | uc-008: a paused workflow is decided from the console (api, ui) |
| `usecases/agents-service/self-approval-refused.md` | uc-009: self-approval is refused |
| `usecases/agents-service/agent-create-publish-chat.md` | uc-018: create, edit, publish an agent and chat with it |
| `usecases/agents-service/workflow-draft-publish-start.md` | uc-019: create a workflow from draft JSON, validate, test, publish and start it |
| `usecases/agents-service/chat-starts-a-workflow.md` | uc-020: chat starts a workflow |
| `usecases/agents-service/approval-outlives-its-token.md` | uc-027: an approval outlives its token |
| `usecases/agents-service/agent-runs-on-its-model.md` | uc-028: an agent runs on the model its publisher chose |
| `usecases/tools-service/failure-side-and-real-reads.md` | uc-038: a failed tool call says which side failed, and a test call reaches the real system |
| `usecases/platform-service/sign-in-and-sessions.md` | uc-021: sign in, session, refresh with rotation, sign out |
| `usecases/platform-service/members-and-roles.md` | uc-023: invites, role changes, the last admin, and a removal that ends sessions and keys |
| `usecases/platform-service/audit-log.md` | uc-025: every member write leaves one entry, and a viewer cannot read them |
| `usecases/platform-service/anonymous-and-dev-boundary.md` | uc-026: no route but the public ones answers without credentials |
| `usecases/tools-service/workflow-approvals-use-agents-service-workflows.md` | uc-041: Workflow approvals use agents-service workflows |
| `packages/usecase-runner/overview.md` | Use case runner: modules, verdict, exit codes, tests |
| `architecture/dependencies.md` | Every third-party Python package in the lock: version, licence, native code, network behaviour (generated by `make sbom`) |
| `architecture/make.md` | How make is organised: root orchestration, fragments by concern, the service verb set, env names, ports, `ISOLATED=1`, the daily commands |
| `services/agents-service/overview.md` | Agents service: modules, graphs on four calls, settings, proofs, where it differs from the specs |
| `services/agents-service/experiments/own-checkpointer.md` | E0: own LangGraph checkpointer on asyncpg with tenant row-level security |
| `services/agents-service/experiments/pause-survives-graph-change.md` | E1: a paused thread survives a graph change by version pinning |
| `services/agents-service/experiments/leases-and-sweeper.md` | E2: thread leases and a sweeper continue a crashed run |
| `services/agents-service/experiments/fencing.md` | E2b: fencing every write a stale lease owner can make |
| `services/agents-service/experiments/fence-on-takeover.md` | E2c: raising the tools-service fence when agents-service takes a thread over |
| `services/agents-service/experiments/conformance-suite.md` | E9: the execution-engine conformance suite on the LangGraph adapter, with its two open gaps |
| `services/agents-service/experiments/gateway-approval-token.md` | E3: tool gateway with OPA and approval tokens bound to the input |
| `services/agents-service/experiments/checkpoint-growth.md` | E4: checkpoint growth |
| `services/agents-service/experiments/checkpoint-per-version.md` | Checkpoints per channel version against whole-state checkpoints: measured, not adopted |
| `services/agents-service/experiments/timers-and-sla.md` | E5: durable SLA timers and a poller for human steps |
| `services/agents-service/experiments/chat-turn-latency.md` | E8: chat turn latency and the platform's overhead |
| `services/agents-service/experiments/models-service-hop.md` | E13: what routing a turn through models-service adds |
| `services/agents-service/experiments/cost-and-budgets.md` | E12: usage per model call, thread budgets that pause for a person, metering overhead |
| `services/agents-service/experiments/mailbox-adapter.md` | E6: mailbox adapter turning Graph delta mail into threads and runs without duplicate cases |
| `services/agents-service/experiments/approval-trust.md` | Approval trust: RFC 8785 hashes, verified step-up, distinct approvers and the self-approval setting |
| `services/agents-service/experiments/events-and-resume.md` | Events and resume: the thread event log, re-attach, team stream, and reviews resumed only through decide |
| `services/agents-service/experiments/chat-on-graph.md` | Console chat as a facade over agent_wrapper threads: a message is a run, approvals go through decide, the old chat tables are dropped |
| `services/models-service/overview.md` | models-service: aliases, keys with budgets, admission and OpenAI-compatible egress with a metadata-only call log |
| `services/platform-service/overview.md` | platform-service: sign-in, sessions, members, invites, API keys and audit; the only token issuer, verified elsewhere through ops_identity |
| `services/tools-service/overview.md` | tools-service: the tool-module registry, calls resolved and validated through it, executors, and the executions log |
| `services/files-service/overview.md` | Files library: uploads, dedupe, scanning hook, retention, legal holds over local, S3 and Azure Blob stores |
| `services/files-service/tests.md` | Files library failure modes and the test guarding each |
| `packages/ops_ingest/overview.md` | Knowledge ingestion library: parsing, splitting, metadata, dedupe, source rules |
| `packages/ops_ingest/tests.md` | Knowledge ingestion failure modes and the test guarding each |
| `plan/implementation-plan.md` |
| `plan/ai-gateway-console.md` | AI gateway console feature: prior art, placement under Govern, pages, contract, open questions (plan only) |
| `plan/agent-completions-through-models-service.md` | Agent turns on their own alias through models-service: what exists, what changes, uc-028, decisions, slices (research note) |

File names are topics. Specs keep their number (01–17; 05 and 06 unused) and decision records their ADR id in the
title, so cross-references such as "spec 03 5.2" or "ADR-0005" still resolve.
