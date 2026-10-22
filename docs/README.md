# Documentation

Status: current. Every document below is a draft for review unless its own status line says otherwise.

These documents design an operational AI platform for banks and describe the console in
`apps/console/` that shows it. Backend code runs for all six services (`services/platform-service`, `services/agents-service`, `services/tools-service`, `services/models-service`, `services/kb-service`, `services/files-service`). Reviews, Cases and work items move into the planned `ops_hitl` package, hosted by agents-service. `architecture/README.md` is the entry page for the system as built.

## Map

<!-- site: cards -->
| Area | Start at | What it holds |
|---|---|---|
| Background | `background/problem-statement.md` | Why bank AI workflows stall and what the platform needs |
| Architecture | `architecture/README.md` | The system as built: services, runtime, human in the loop, identity, data, operations, and the decision records in `architecture/decisions/` |
| Design, by area | The design table below | Proposed and approved designs with their wireframes and mocks: workflows and agents, tools, human tasks, cases, chat, data, and the prior-art research behind them |
| Console | `console/page-plan.md` | Console pages, the UI standard, user guides, and screens approved (`console/approved/`) or waiting for approval (`console/proposed/`) |
| Services and packages | `services/<name>/overview.md`, `packages/<name>/overview.md` | One page per service and library: what it does, its routes and tables, its tests |
| Deploy | `deploy/install-guide.md` | Installing and running Ops AI: Compose, Kubernetes, the database, the release package |
| Client guide | `guide/README.md` | One architecture and installation guide for a client team, the source of `deploy/client-install-guide.html` |
| Use cases | `usecases/README.md` | The end-to-end checks that prove each feature, and how to run them |

## Design

Each page opens with the problem it solves and says what is built. Images sit beside each area in `images/`.

| Path | Topic |
|---|---|
| `design/workflows/workflows-and-agents.md` | Agents and workflows as two ways of running work on shared services: stories, entities, state machines, the run, review and trigger APIs, the Node SDK, capability packs, portability, scale, security and the slice plan |
| `design/workflows/workflow-nodes.md` | Node types and instances, typed ports, the catalogue, files owning reading, the court order notice as a worked example, and the runner options weighed |
| `design/workflows/canvas.md` | The workflow canvas mock the editor is built to: step list, step sheets, checks, shortcuts, themes and phone width |
| `design/tools/tool-system.md` | One tool model for HTTP, MCP, workflows, agents, platform services and code; connections and sign-in kinds; one value syntax; test and production; the editor slices with wireframes |
| `design/tools/mcp-server.md` | Serving governed tools over MCP per team and environment through the gateway: OAuth, held writes, masking, rate limits, console wireframes |
| `design/human-tasks/task-page.md` | The Human Task page: one question per task, the full page with a footer row, task types as versioned records, wireframes |
| `design/cases/case-page.md` | One generic case layout configured per workflow, shown for a tax order, a complaint and a KYC review, and the case read it needs |
| `design/chat/embedded-chat-screens.md` | The embedded chat on an intranet page, state by state: closed, open, phone, approval, answer widget, streaming, signed out, session ended |
| `design/data/sql-server.md` | Running on SQL Server and Azure SQL beside PostgreSQL: the coupling inventory, the mapping, tenant isolation, migrations, proof and phases |
| `design/data/database-packages.md` | Database code only in each service's store package: the layout, the import contracts, and what not to do |
| `design/research/agent-run-api.md` | Prior art: how agent platforms build chat over a run API and run agents without chat |
| `design/research/node-sdk-and-forms.md` | Prior art: how workflow tools define nodes, settings forms, credentials, triggers and versions; a recommended Node SDK contract |
| `design/research/forge-workflow-study.md` | A study of an open-source workflow engine on LangGraph, concern by concern |
| `design/research/workflow-node-improvements.md` | Ten workflow node improvements compared across workflow products, with what is built since |

## How the docs site shows a page

The docs site (`apps/docs`, served under `/docs`) renders these files as they are; there is no second copy. Write
plain markdown that reads well on GitHub; the site maps a few conventions onto its components. This table is the
shared list: the shareable guide built from `guide/*.md` is meant to present the same markdown the same way.

| Write | The site shows |
|---|---|
| `# Title` as the first line | The page title (and its sidebar name) |
| `Status: proposed design. ...` as the first paragraph | A status line with a badge for the opening words |
| A table cell starting with `built`, `partial`, `planned` or `not built` | That word as a green, amber, blue or grey badge |
| `<!-- site: cards -->` directly above a table or a list | Summary cards: a table row or list item each; the first cell, or the item's opening **bold** or link, is the title |
| `<!-- site: steps -->` directly above a numbered list | Numbered steps |
| `> [!NOTE]`, `> [!WARNING]` (GitHub alerts) | A callout |
| A ```` ```mermaid ```` block (flowchart, sequence, state, ER) | The diagram in the site's theme |
| `![caption](../diagrams/<name>.svg)` where `diagrams/<name>.yaml` exists | The live architecture diagram drawn from that data file; GitHub shows the exported SVG |
| Any other image alone in a paragraph | A framed figure with the alt text as its caption |
| A relative link, or a code span naming a file (`services/x/y.py:42`) | A link to the page here, or to the file on GitHub |

A link to a page or file that does not exist fails the site build, and so does a diagram SVG that no longer matches
its data file. Edit a diagram in `diagrams/<name>.yaml`, then run `pnpm --filter docs diagrams` to export its SVG.

## Reading order

| Reader | Read in this order |
|---|---|
| Engineer | `background/problem-statement.md` → `architecture/overview.md` → `architecture/service-map.md` → the topic spec for the area you work on → `plan/implementation-plan.md` |
| Architect | `background/problem-statement.md` → `architecture/overview.md` → `architecture/decisions/` (ADR-0001 to ADR-0016; every ADR is an option, not decided, until it is confirmed) → [tool system design](design/tools/tool-system.md) → `architecture/service-map.md` |
| Risk reviewer | `background/problem-statement.md` → `architecture/overview.md` (traceability, failure modes) → [ADR-0012 Assurance: governance and testing as one system](architecture/decisions/assurance.md) → ADR-0005 |

## Requirements

| # | Requirement | Where it is met |
|---|---|---|
| 1 | Implement the problem statement: seven reasons, three decisions and the model-traffic mandate, four components, edit classes, ten knowledge requirements | Every spec; traceability in `architecture/overview.md` |
| 2 | Deliver the email-to-workflow reference flow: mailbox, understand, route to case, queue and SLA, drafted actions with per-action approval | [agents and workflows](console/agents-and-workflows.md), [tool system design](design/tools/tool-system.md) |
| 3 | Fix the architecture first, with each decision stating options, criteria, evidence and what would change it | `architecture/decisions/` |
| 4 | Build on open source (Temporal and peers) so existing implementations can plug in | ADR-0001, ADR-0007 |
| 5 | Choose the implementation language on the merits | ADR-0002 |
| 6 | Keep workflows and agents portable to other platforms; assess the Agent Workflow Protocol (AWP) and adjacent standards | ADR-0003 |
| 7 | One spec per topic | One page per topic under `architecture/` and `design/` |
| 8 | Apply lessons from earlier agent platforms; the agents are internal and not voice or customer facing | The decision records, each with the lessons it applies |
| 9 | Treat the console as the UI reference; each spec states what each screen needs from the backend | "UI mapping" section of each spec |
| 10 | The bank runs no workflow or agent runtime today, so the runtime choice is greenfield; existing agents stay behind adapters | ADR-0001 |
| 11 | Judge every decision on the marginal effort of the next workflow, not only the first | `architecture/overview.md` (throughput), each spec's "Marginal effort" section |
| 12 | Staff chat with agents inside the platform, with MCP Apps for in-chat data views | [chat in the console](console/chat.md), ADR-0009 |
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
| `architecture/agent-guardrails.md` | Guardrails and skills an agent pins by version: the classification check before and after the answer, fail-closed exits, skill loading and caps, what is enforced and what is not |
| `architecture/workflows-as-tools.md` | Workflows as agent tools: an agent starts a published workflow as a child thread and gets its result or a review handle |
| `architecture/human-in-the-loop.md` | Interrupt kinds, review rules, approval tokens, step-up, two approvers, SLA timers, pauses per channel |
| `architecture/tool-lifecycle.md` | A tool from connect to import, review, access, grant, call, write approval and display; built versus target; the per-operation approval policy |
| `architecture/workflow-runner.md` | Workflow runner: LangGraph with a step journal, Postgres queue and workers; the ops_engine split from agents through ports; resilience, scale, console, versioning, proof |
| `architecture/channels-and-deployments.md` | Deployments, the adapter contract, identity and keys per channel, busy-thread input, the mailbox adapter |
| `architecture/identity-and-tenancy.md` | Sign-in seam, delegation, process principals, tools gateway, row-level security, prototype shortcuts |
| `architecture/definitions-and-versions.md` | Draft to publish, pointers, the pin per thread, what happens without it, migrate |
| `architecture/durability-failure-and-audit.md` | Leases, sweeper, fencing, re-execution, idempotency, side-effect classes, journal, checkpoint growth and pruning |
| `architecture/data.md` | Tables per service, the checkpointer package, designed stores, retention |
| `architecture/operations.md` | Running it, environments, health, the acceptance gate, what to watch, runbooks |
| `architecture/enterprise-architecture.md` | One-page picture for an enterprise: identity, observability and secrets bands, the platform, both gateways, and how to build, develop and deploy it, with status per part |
| `architecture/data-model.md` | Every table, grouped by owning service, with keys, links, status per table and the database portability rules; companion to the architecture page |
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
| `architecture/decisions/database-support.md` | ADR-0017, decided: PostgreSQL and SQL Server 2025 (Azure SQL first in intent), MySQL dropped, and the rule every change follows |
| `plan/implementation-plan.md` | Phases, teams, workstreams, stop condition |
| `console/chat.md` | Chat: the AI Elements blocks behind chat-blocks.tsx, untrusted replies, widget shapes and the registry, x-ops-shape, adding data not components |
| `console/agents-and-workflows.md` | User guide: what an agent is made of, chatting, agents as workflow steps, workflows as tools, when to use which |
| `plan/banker-demo.md` | Banker demo stage scripts: the court order notice from the fake mailbox to a held account, and the two agents answering from seeded knowledge bases; before-the-room checks, model switch, failure tables |
| `deploy/fly.md` | Ops AI staging on Fly: one app per image in your Fly org, the shared Postgres, creating, deploying, connecting the model, logs, rolling back and the monthly cost |
| `deploy/database.md` | The database for a DBA: roles and who runs what, the baseline for a fresh install, guarded upgrades between releases, drift, the start check, roll back and the proof |
| `deploy/kubernetes.md` | Ops AI on Kubernetes: the Kustomize base per service and overlays, probes, per-service Secrets, the migrate Job, an outside PostgreSQL, install, upgrade and the kind proof |
| `deploy/compose.md` | Ops AI on Docker Compose against the bank's PostgreSQL: the images, what runs, the facts that shape it, running from a clean clone, connecting a model, secrets as files, upgrade, back up and logs |
| `deploy/fly-staging.md` | Staging on one Fly machine: what runs, the facts that shape the image, the commands that create the app, first-run steps, deploy and roll back, and a local run |
| `deploy/docs-site.md` | The docs site (`apps/docs`) on Vercel: project settings, the static build under `/docs`, and serving it at a path of another host |
| `deploy/release-package.md` | The release package a client team installs from: `make release-package`, what it holds, the proof from the tarball alone, the facts that shape it and what pushing the images would need |
| `deploy/install-guide.md` | Generated from `guide/install.md` and `guide/operate.md` and shipped in the release package as INSTALL.md: install with install.sh, then status, logs, upgrade, back up, restore and scaling |
| `deploy/install.md` | `./install.sh` from a clone: what it asks, what it does, the other commands (upgrade, backup, restore, status, logs, uninstall), what is proven, and the by-hand appendix |
| `deploy/client-install-guide.html` | The client architecture and install guide as one shareable page, generated from `guide/` by `scripts/docs/build_guide.mjs` |
| `guide/README.md` | The client guide's index: the twelve sections in order and what each holds |
| `guide/overview.md` | What Ops AI does, for whom, the platform map and the ideas it rests on |
| `guide/system-components.md` | Every container: purpose, port, what it stores and what it calls |
| `guide/how-work-flows.md` | A chat turn with a tool approval, a workflow with a human task, and a court order notice emailed to a team mailbox |
| `guide/data-and-database.md` | The entities, each service's tables, tenant and team isolation, files and knowledge, retention and the audit trail |
| `guide/security-and-governance.md` | Sign-in and SSO, roles, approvals, the tool gateway and allow-list, secrets, masking, hardening |
| `guide/models.md` | The AI gateway: aliases, keys, budgets, data sensitivity and the test model |
| `guide/deployment-options.md` | Compose, Kubernetes, single- and multi-tenant, the network and sizing |
| `guide/install.md` | What to arrange before an install, then the install script's steps, included from `deploy/install.md` |
| `guide/operate.md` | Health, logs, upgrade and roll back, back up and restore, scaling, what to watch, key rotation |
| `guide/azure-sql.md` | Azure SQL: the scripts ready for review and what is still to come |
| `guide/whats-built-today.md` | Built, partial or planned, capability by capability |
| `guide/support.md` | The support contact (placeholder) |
| `console/page-plan.md` | Console pages and the rules every page follows |
| `console/standards.md` | Console UI standard: tokens, layout primitives, compose-from-shadcn, designed states, responsive, one-screen create, and the review checks |
| `console/ui-qa.md` | UI QA pass: one section at a time in a browser, checking what works, how easy it is and how it looks, with a findings table |
| `console/channels-preview.md` | The channels design mock at /preview/channels: the gallery, every connection, connect a mailbox as a page and a dialog, the trigger sheet that picks it, and the server routes the real build needs |
| `console/approved/channels/README.md` | The Channels screens the maintainers approved, at 1280 and 400 px, which the real pages are built to |
| `console/proposed/files/README.md` | The file page and Extract screens built by c-262, at 1280 and 400 px, waiting for the maintainers' approval |
| `console/proposed/reuse-c266/README.md` | Start run, run and case pages before and after c-266, side by side |
| `console/proposed/tasks/README.md` | The Human Task page built by c-289 beside wireframes A and B of the v2 design, at 1280 and 400 px, waiting for the maintainers' approval |
| `console/proposed/table-columns/README.md` | The shared data table's columns sized by kind, before beside after for Workflows, Runs, Files and Members at 1280 and 400 px |
| `console/proposed/run-status/README.md` | Run status from where a run ended and from the runs it started: failed and waiting runs before beside after, and the End step's Counts as, at 1280 and 400 px |
| `console/settings-tree.md` | The settings tree design mock at /preview/settings: the pages, the patterns, the dialogs with their mother pages, and the field kit |
| `console/strategy.md` | Console strategy: thin UI over a generated SDK, per-page audit with verdicts, the agentic core slice, chat on the thread calls, what to stop |
| `console/tools-design.md` | Design of the tool module screens |
| `console/embedding-the-chat.md` | How a bank embeds the chat: widget deployment, the bank's session endpoint, the script tag, events, errors, security properties and a local test (built and planned parts marked) |
| `console/mailbox-demo.md` | Runbook: `make up AUTH=platform` then `make demo-mailbox`, and the console pages to show the emailed court order notice on |
| `console/demo-script.md` | The demo, scenario by scenario: where to go, what to type and what the viewer sees, each proven by `make demo-sweep` |
| `usecases/README.md` | Use case registry: how to run, rules (scripted model only, PASS needs evidence), layout, exit codes |
| `usecases/agents-service/chat-turn-with-citation.md` | uc-001: chat turn with citation |
| `usecases/agents-service/test-an-agent-on-a-real-thread.md` | uc-247: A builder tests an agent on a real chat thread the server marks test |
| `usecases/agents-service/test-an-agent-in-its-page-panel.md` | uc-253: A builder tests an agent in the right panel of its page, with the chat page's components |
| `usecases/agents-service/typed-human-tasks.md` | uc-254: A builder copies a task type and an API caller opens typed Human Tasks |
| `usecases/agents-service/workflow-ai-steps.md` | uc-258 to uc-262: A workflow uses AI steps without a saved agent |
| `usecases/agents-service/task-assist.md` | uc-263: A typed task opens with task assist when the team turns it on |
| `usecases/agents-service/personal-data-masked.md` | uc-265: Personal data is masked in an agent's replies, stored messages and workflow step output |
| `usecases/tools-service/check-before-sending.md` | uc-266: A workflow's write is checked against the team's sending policy before it goes out |
| `usecases/agents-service/calculate-a-levy-amount-and-deadline.md` | uc-231: A Calculate step works out a court order's amount and deadline |
| `usecases/agents-service/write-tool-approval-step-up.md` | uc-002: write tool pauses and approval resumes with step-up |
| `usecases/agents-service/simple-workflow.md` | uc-003: simple workflow through the four thread calls |
| `usecases/agents-service/complex-workflow.md` | uc-004: complex workflow with fan-out, grade loop, review pause and send |
| `usecases/agents-service/pause-survives-restart.md` | uc-005: a pause survives a restart |
| `usecases/agents-service/sla-breach-escalates.md` | uc-006: SLA timer breach escalates |
| `usecases/tools-service/write-without-token-refused.md` | uc-007: a tool write without a token is refused |
| `usecases/tools-service/notify-a-webhook.md` | uc-230: A workflow step notifies an outside system's webhook with a case's data |
| `usecases/tools-service/connections-api-key.md` | uc-390: A tool signs in with an API key from its connection, by environment |
| `usecases/tools-service/connections-basic.md` | uc-391: A tool signs in with a username and password from its connection, by environment |
| `usecases/tools-service/connections-bearer.md` | uc-392: A tool signs in with a bearer token from its connection, by environment |
| `usecases/tools-service/connections-client-credentials.md` | uc-393: A tool signs in with an OAuth client ID and secret |
| `usecases/tools-service/connections-sign-in.md` | uc-394: A person signs a connection in once with the team's account |
| `usecases/tools-service/connections-certificate.md` | uc-395: A tool presents a client certificate from its connection |
| `usecases/tools-service/mcp-sign-in.md` | uc-396: A builder adds an MCP server behind OAuth and its tools run through the same executor |
| `usecases/tools-service/mock-answers.md` | uc-397: A workflow's tool step reaches its error and timeout ports on mock answers |
| `usecases/tools-service/mcp-server.md` | uc-410: An assistant lists and runs a team's read tools over MCP with an API key |
| `usecases/tools-service/manage-tool-modules.md` | uc-010: a builder creates, versions and approves a tool module, and it survives a restart |
| `usecases/tools-service/calls-through-the-registry.md` | uc-011: a tool call runs through the registry and is logged with its caller |
| `usecases/tools-service/import-tools.md` | uc-012: tools imported from OpenAPI and MCP, called only on hosts and ranges the tenant allows |
| `usecases/tools-service/secrets.md` | uc-013: a tool's credential is a secret, sent at call time and never returned |
| `usecases/console/tool-lifecycle-end-to-end.md` | uc-055: James imports the bank, Nadia reviews, James grants, the agent reads and holds, Maya approves in Reviews; US1 to US5 of c-048 on the shared stack |
| `usecases/console/channels-preview.md` | uc-165: James connects a Gmail mailbox with a secret added from the field, tests it, and a workflow trigger picks it; the mailbox page then lists the workflow |
| `usecases/console/knowledge-bases-end-to-end.md` | uc-096: James creates a knowledge base, adds files and a page, watches them index (a scan fails with its reason), tests a question in the playground and retires the base |
| `usecases/console/edit-an-operation.md` | uc-090: James edits an operation's input in a form (a wrong-typed default refused on its field, an optional field minor, a required one major), sets step-up and access, and sees the secrets it reads as set or not |
| `usecases/console/import-to-governed-call.md` | uc-086: James stores the bank's keys as secrets, imports its OpenAPI document, Nadia approves it on the module page, a second version publishes, the agent reads and holds, Maya approves and the bank holds once; the call log names actor, approver and outcome |
| `usecases/console/chat-find-start-continue.md` | uc-087: James starts a chat from a suggested prompt, regenerates, stops a slow reply, retries a refused send, pages his chats by cursor and finds an old one by its question through server search |
| `usecases/console/chat-overrides-within-limits.md` | uc-091: the thread settings panel offers only what the agent allows; a switched-off tool is not offered; each turn records its settings; an attached PDF is cited by page |
| `usecases/console/stale-grants-removed.md` | uc-056: a grant whose operation is no longer offered shows in the grant dialog and saving drops it |
| `usecases/console/chat-act-in-thread.md` | uc-072: Maya gets a cited answer, approves a drafted wire hold in the thread after a step-up and rejects another with a reason |
| `usecases/console/knowledge-from-uploaded-pdfs.md` | uc-075: James creates a knowledge base with its owner, uploads a PDF into a file source, watches it index, asks an agent granted only that base and opens the citation and document; a second version shows on Changes |
| `usecases/console/advisor-helper-answers.md` | uc-078: the Advisor's Helper draws a customer's record and accounts, cites the product sheet by page and shows the comparison as a table |
| `usecases/console/branch-policy-answers.md` | uc-079: the Branch Policy agent cites the manual and fee schedule by page, says when the answer is not in the knowledge base, and cites version 2 after a replacement (blocked on c-055 T024) |
| `usecases/console/chat-thread-blocks.md` | uc-074: the chat thread draws a cited answer (citation button, no raw marker) and a tool card with AI Elements blocks |
| `usecases/console/widgets-through-chat.md` | uc-061: a granted agent's tool results stream in as widgets by shape (declared shape wins, unshaped stays a tool card) and survive a reload |
| `usecases/console/agent-presents-widgets.md` | uc-089: an agent with no tools shows a table and a stat through the built-in present tool; a shape present does not allow draws nothing |
| `usecases/console/agent-fills-widgets.md` | uc-095: an agent pins a widget on its page, fills it in chat, a button sends its reply, and it lays out its own from the catalogue |
| `usecases/console/forms-save-on-enter.md` | uc-097: James saves a new widget and a new guardrail with Enter; Cancel and Enter in a tag field save nothing; Enter on the sample-data account name saves nothing |
| `usecases/console/lists-page-on-the-server.md` | uc-098: James pages Guardrails and searches it, and each page and search is answered by agents-service |
| `usecases/console/dialogs-save-on-enter.md` | uc-110: Sam adds a host and a secret with Enter; Cancel in Add host sends no request |
| `usecases/console/files-page-on-files-service.md` | uc-112: James searches Files, sees what uses a file, downloads it and deletes an unused one; Priya places a legal hold |
| `usecases/console/pickers-search-the-server.md` | uc-113: James searches the agent page's knowledge picker for the 118th base and grants a tool; the version stores their ids |
| `usecases/console/viewer-sees-read-only-pages.md` | uc-099: Ravi, a viewer, sees no create button and opens an agent read-only; James, a builder, sees and edits them |
| `usecases/console/console-matches-page-plan.md` | uc-100: the Overview shows only what waits on a person, Agents has no Templates, Chat reaches Conversations, and roles say reviewer |
| `usecases/console/lists-preview-and-versioned-saves.md` | uc-106: a 25-row list is one Tab stop per row; Settings shows Preview beside real services and Egress does not; Enter in Storage saves no version and the Save button does |
| `usecases/console/widget-edited-with-forms.md` | uc-103: James adds a widget field, its sample and a caption bound to it with forms; the saved template keeps the JSON limits |
| `usecases/console/guardrail-record-page.md` | uc-104: James saves and publishes v2 on a guardrail's page, sees both versions, and pins v1 on an agent |
| `usecases/console/storage-settings-per-purpose.md` | uc-105: Sam adds a storage credential that is never shown again, points chat attachments at their own target, and a target that fails its test is refused |
| `usecases/console/chat-budget-continue.md` | uc-108: James's chat pauses on a one-call budget, he continues it; Priya, an admin, raises hers; the wrong person is refused |
| `usecases/console/widget-embed-second-origin.md` | uc-109: James embeds an agent from its Channels tab; Maya chats through the snippet on the intranet origin; another origin is refused |
| `usecases/console/role-hidden-run-and-review-controls.md` | uc-123: a viewer sees no run button on a workflow; a builder does |
| `usecases/agents-service/extract-from-file.md` | uc-124: an Extract from file step reads an invoice into cited, scored fields; invented quotes, high thresholds and the tenant floor go to review; a scan without OCR is unreadable |
| `usecases/agents-service/email-starts-a-workflow.md` | uc-150 and uc-151: an email with a PDF in a watched mailbox starts one workflow run with the PDF in Files, a redelivery starts none; Email received is set up on the canvas |
| `usecases/agents-service/imap-mailbox-starts-a-workflow.md` | uc-192: an email with a PDF in an IMAP mailbox starts one workflow run through tools-service; the password is a Secrets-page secret |
| `usecases/agents-service/connect-a-mailbox.md` | uc-199: a builder connects a team mailbox on Channels > Email, tests it, binds a workflow, pauses and resumes it |
| `usecases/agents-service/reply-from-a-team-mailbox.md` | uc-200: a send_reply naming a team mailbox leaves from its own sender, for the calling team only |
| `usecases/agents-service/start-a-workflow-per-item.md` | uc-209: a Start workflow step starts a child workflow for each item of a list |
| `usecases/agents-service/levy-on-the-runner.md` | uc-210: a court order notice runs on the workflow runner from its mailbox |
| `usecases/agents-service/mailed-documents-become-cases.md` | uc-223: documents emailed to a team mailbox become cases, and the sender gets a reply |
| `usecases/agents-service/team-default-agent.md` | uc-128: chat starts on the team's default agent, which asks specialists |
| `usecases/agents-service/agent-test-shows-steps.md` | uc-133: a test reply shows the knowledge searched and cited, the tools called and where it would pause |
| `usecases/agents-service/agent-remembers-each-person.md` | uc-134: an agent remembers each person, who lists, corrects, exports and forgets what it keeps |
| `usecases/agents-service/people-manage-agent-memory.md` | uc-135: people see, correct, forget and export what an agent remembers, from the chat |
| `usecases/console/embed-agent-chat-from-console.md` | uc-136: embedding an agent's chat works end to end from the console |
| `usecases/console/publish-review-applies-at-once.md` | uc-137: a changed publish review setting applies to the next tool module publish |
| `usecases/console/record-pages-follow-record-flags.md` | uc-138: knowledge, source and file pages follow each record's own flags |
| `usecases/console/cases-console.md` | uc-139: the console works cases |
| `usecases/console/demo-walk.md` | uc-140: the demo walk on the shared stack |
| `usecases/console/activity-page.md` | uc-141: the one Activity page on /v1/activity |
| `usecases/console/channels-real.md` | uc-142: Channels on real data, checked against /v1/channels |
| `usecases/console/tool-access.md` | uc-143: Access › Tool access on tools-service's grants list |
| `usecases/console/file-extraction.md` | uc-227: a file opens on its own page, Extract reads it with a document type, and Files says how each file was read |
| `usecases/console/start-run-and-records.md` | uc-228: the start-run dialogs, a run page and a case page, with screenshots for a before-and-after comparison |
| `usecases/console/human-task-page.md` | uc-234: a Human Task opens as its own page, with the question, the document beside the read values, Details folded and the decision in a footer row below the body |
| `usecases/console/access-roles-and-checks.md` | uc-267: an admin reads Access › Roles and a built-in role's grid read-only, a member's access beyond their team role on Members, and a person's effective access with the role behind each action |
| `usecases/console/demo-team-shows-each-once.md` | uc-450: on staging the demo team's Open cases and run picker show each record once, and Dispute Desk finds Marcus Bell's Coastal Air charge at the bank |
| `usecases/console/every-page-has-the-header.md` | uc-264: every sidebar route and one record of each kind render the shared page header; the runtime half of check-standards rule 12 |
| `usecases/console/services-unreachable.md` | uc-404: a link to a missing task says so; a session ended elsewhere goes back to sign-in keeping the page; with the run's platform-service stopped, one shell screen says the services are out of reach, with Try again |
| `usecases/console/case-page-assembled.md` | uc-256: a case opened by a configured workflow shows its header and next action, fields in the case type's order, the task it waits on, the drafted action, linked records and recent activity from one case request; approved, the action reads approved |
| `usecases/console/pdf-scripts-never-run.md` | uc-398: a crafted PDF carrying open-action, link and form-field scripts is drawn by the file viewer and none of its scripts run; the worker loaded is PDF.js 6.2.108 or later |
| `usecases/console/table-column-kinds.md` | uc-257: tables size each column by what it holds, with names trimmed to one line, numbers right-aligned, a dash for an empty cell and the name pinned on a phone |
| `usecases/console/shell-real-data.md` | uc-232: the header's workspace name and Tools › Workflows come from the services, not the mock |
| `usecases/console/run-with-files.md` | uc-233: Start run is a form from the trigger's input schema, with files uploaded or picked |
| `usecases/console/agent-channels.md` | uc-130: an agent's Channels tab shows its chat default, embeds with sites, keys and usage, and calling workflows; an embed retires for good |
| `usecases/console/agent-shows-every-widget-kind.md` | uc-132: the agent shows every generic widget kind in a chat, each drawn once from its schema-checked data |
| `usecases/console/widget-mint-keys.md` | uc-116: James creates an embed's mint key, the secret shown once; the server mints with it; revoked, it mints nothing; a viewer sees no key controls |
| `usecases/console/embedded-chat-on-a-bank-page.md` | uc-119: a bank page opens the full chat through the loader and the embed app; a hold waits for Human Tasks; forged messages and unlisted pages refused |
| `usecases/agents-service/widget-mint-and-approve.md` | uc-117: the bank's server mints with the deployment's key, the chat's hold is decided through Reviews, team and revoked keys refused |
| `usecases/console/widgets-by-shape.md` | uc-073: every chat widget shape draws with its default renderer on /dev/widgets, switches between chart and table, and records approve and submit |
| `usecases/console/write-approval-policy.md` | uc-059: a builder sets a write's approvers, approving team and self-approval in the operation sheet, and the operation shows them |
| `usecases/console/chat-read-only-for-others.md` | uc-058: another person's chat stays private; a teammate gets 404 and the maintainers keeps the message box |
| `usecases/console/chat-holds-in-reviews.md` | uc-057: a write held in a chat appears in Reviews marked From chat and is approved there |
| `usecases/console/levy-cases-decided.md` | uc-077, retired (c-212): the v1 court order run's cases decided from the console |
| `usecases/console/import-presets-access.md` | uc-054: import presets Read for GET and Write otherwise, warns when a spec has no auth, and asks for no connection |
| `usecases/console/workflow-access-approved-by-another-person.md` | uc-053: Approve compares the signed-in person with the requester; James requests, Priya approves |
| `usecases/console/access-is-read-or-write.md` | uc-052: no console control or badge offers a "Moves money" class; access is Read or Write |
| `usecases/console/sub-pages-in-the-sidebar.md` | uc-047: every sidebar parent lists its sub-pages as rows, the active one lit, closed parents remembered |
| `usecases/console/tool-workbench.md` | uc-101: an operation on its full-width workbench; draft mock and transform, a secret typed for one run, the request sent masked, the mock staged for review |
| `usecases/console/secrets-in-one-place.md` | uc-107: Settings > Secrets lists the operations each secret serves, a rotation reaches them all, a delete in use is refused, and a team scope is enforced by the gateway |
| `usecases/console/sample-data-pages-say-so.md` | uc-125: a page the mock stores shows "Sample data, changes aren't saved" and cannot be saved, while a live setting keeps its value after a reload |
| `usecases/console/settings-tree-mock.md` | uc-126: the proposed settings tree at /preview/settings: one set of cards, Find, role locks, and dialogs that are the same forms as the pages |
| `usecases/console/layout-rules-sweep.md` | uc-127: fields lighter than the page, the widget definition splits with a handle, tab labels fit, and record lists start with select-all and an id column |
| `usecases/console/settings-tree-live.md` | uc-152: settings has its own sidebar with Find, and each moved page answers at its new route while the old route redirects |
| `usecases/console/policies-page.md` | uc-170: Govern > Policies lists the workspace policies from platform-service; a Security admin saves one, a builder is refused in the server's words |
| `usecases/console/run-on-the-canvas.md` | uc-115: a run opens on its workflow's canvas with each step marked passed, failed or skipped, and a step's input and output one click away |
| `usecases/console/workflow-canvas.md` | uc-121: the workflow editor's canvas fills the page with the sidebar collapsed, at a readable zoom, with floating controls, checks and minimap |
| `usecases/console/edit-steps-in-a-sheet.md` | uc-122: a workflow step and the trigger open in a sheet beside the canvas, and steps are added from a panel with a tab per group and a search |
| `usecases/console/start-run-form.md` | uc-445: Start a run opens the chosen workflow's form at once, names fields by their titles, offers choices as selects, and uploads or picks a file |
| `usecases/console/start-from-the-trigger.md` | uc-466: Start run draws the trigger's start form; a test email runs as a mailbox email does; Files starts a workflow with a file |
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
| `usecases/agents-service/agent-calls-registry-operations.md` | uc-048: an agent is granted a published tools-service operation and calls it through the gateway |
| `usecases/agents-service/write-approval-policy.md` | uc-049: a write runs only after as many distinct people as its operation's policy names approve it |
| `usecases/agents-service/levy-from-mailbox.md` | uc-076, retired (c-212): the v1 court order flow from the mailbox deployment; uc-210 replaces it |
| `usecases/agents-service/workflow-runner-basic-nodes.md` | uc-081: basic workflow nodes run through the queue and survive a worker crash |
| `usecases/agents-service/agent-runs-a-workflow-by-search.md` | uc-084: an agent finds a workflow with search_tools and runs it; its agent step answers by schema |
| `usecases/agents-service/agent-guardrails-blocked-topics.md` | uc-085: an agent refuses a blocked topic before answering, through a guardrail it pins by version |
| `usecases/kb-service/knowledge-cited-answers.md` | uc-080: uploaded PDFs indexed by page and section; a granted agent cites them in chat; a replaced document leaves a change row |
| `usecases/kb-service/add-documents-from-files.md` | uc-129: Add documents on a base uploads to Files or picks from it; both index and Files keeps them referenced |
| `usecases/kb-service/people-and-services-read-knowledge-usage.md` | uc-399: People and services read knowledge usage, refs, search and workflow refs on one route each |
| `usecases/files-service/file-lifecycle.md` | uc-093: James stores a PDF through files-service's proxy route; download waits for the scan hook; Priya holds it and delete is refused; released, it deletes |
| `usecases/files-service/file-team-boundary.md` | uc-094: another team's admin gets 404 on every files-service route for a file it does not own; another tenant's service gets 404 |
| `usecases/files-service/a-file-is-read-with-detect.md` | uc-331: A file is read with Detect from the Files page |
| `usecases/tools-service/failure-side-and-real-reads.md` | uc-038: a failed tool call says which side failed, and a test call reaches the real system |
| `usecases/platform-service/sign-in-and-sessions.md` | uc-021: sign in, session, refresh with rotation, sign out |
| `usecases/platform-service/password-sign-in-and-reset.md` | uc-160: a mailed reset link sets a hashed password once and ends the old sessions |
| `usecases/platform-service/oidc-sign-in-creates-a-chat-user.md` | uc-161: a first OIDC sign-in makes one chat-only member; the console offers SSO for the email |
| `usecases/platform-service/saml-sign-in-and-step-up.md` | uc-162: SAML sign-in, and a step-up at the same provider that must ask again |
| `usecases/platform-service/wrong-sign-in-provider-refused.md` | uc-163: a password in an SSO-only workspace, another provider's answer and a reused code are refused |
| `usecases/platform-service/workspace-admins-manage-teams.md` | uc-164: workspace admins create, rename, archive and restore teams; an archived team leaves tokens |
| `usecases/platform-service/workspace-security-default-teams-and-groups.md` | uc-212: a workspace sets its security and default teams; SSO groups map new people to teams |
| `usecases/platform-service/sign-in-providers-and-domain-proof.md` | uc-213: a Security admin sets an OIDC provider on Settings > Sign-in; its domain routes sign-in only once its DNS TXT record is verified |
| `usecases/platform-service/wrong-passwords-lock-sign-in.md` | uc-214: five wrong passwords lock sign-in and step-up; reset mail is capped and a reset ends the lock |
| `usecases/platform-service/saml-signed-requests-and-encrypted-assertions.md` | uc-215: SAML with signed requests and encrypted assertions; another key, old key transport and a plain assertion refused |
| `usecases/platform-service/role-viewer.md` | uc-216: a person invited as a viewer reads the team's work and changes none of it |
| `usecases/platform-service/role-builder.md` | uc-217: a person invited as a builder builds agents and asks to publish, and decides nothing |
| `usecases/platform-service/role-reviewer.md` | uc-218: a person invited as a reviewer decides a builder's publish request and edits no agent |
| `usecases/platform-service/role-admin.md` | uc-219: a person invited as an admin invites, changes roles and removes members in their team only |
| `usecases/platform-service/role-security-admin.md` | uc-220: a person invited as a Security team admin sets sign-in and policies; the right moves with the team |
| `usecases/platform-service/members-and-roles.md` | uc-023: invites, role changes, the last admin, and a removal that ends sessions and keys |
| `usecases/platform-service/audit-log.md` | uc-025: every member write leaves one entry, and a viewer cannot read them |
| `usecases/platform-service/anonymous-and-dev-boundary.md` | uc-026: no route but the public ones answers without credentials |
| `usecases/platform-service/signed-in-across-make-up.md` | uc-111: a person stays signed in when make up brings the stack up again on newer code; the database migrates in place |
| `usecases/platform-service/roles-and-permissions.md` | uc-118: an admin reads the built-in roles and their grids, what a person may do in shared teams, and a role change reaching the next token |
| `usecases/tools-service/workflow-approvals-use-agents-service-workflows.md` | uc-041: Workflow approvals use agents-service workflows |
| `usecases/models-service/an-alias-reaches-the-fake-openai.md` | uc-060: An alias reaches the fake OpenAI or the real one by its connection's base URL |
| `usecases/agents-service/agent-limits-published.md` | uc-088: A builder sets the limits callers override within and publishes them with the agent |
| `usecases/agents-service/workflow-lifecycle-and-forms.md` | uc-092: a builder edits every built step type in its form, publishes through review, runs live to the End output, pauses, resumes and cancels a run |
| `usecases/agents-service/publish-review-policy.md` | uc-114: An admin decides which publishes need a review: never publishes at once, always opens a review, a builder cannot change it |
| `usecases/agents-service/a-person-corrects-a-document-read.md` | uc-224: A person corrects a document read in Human Tasks and sees the reply and cases |
| `usecases/agents-service/a-file-is-extracted-and-purged.md` | uc-244: Extract on a file saves what was read, and deleting the file purges it |
| `usecases/documents-service/builders-manage-document-types.md` | uc-243: Builders manage document types, versions, samples and test runs in the console |
| `usecases/documents-service/every-fixture-is-read-end-to-end.md` | uc-250: Every fixture of four document types is read end to end |
| `usecases/agents-service/a-reviewer-takes-a-workflow-human.md` | uc-225: A reviewer takes a workflow Human Task and sees its deadline |
| `usecases/agents-service/a-guarded-answer-streams-and-is-replaced.md` | uc-229: A guarded answer streams as it is written and is replaced when its check fails |
| `usecases/agents-service/every-shape-of-email.md` | uc-226: A mailbox workflow takes every shape of email |
| `usecases/agents-service/a-team-s-mailbox-runs-end.md` | uc-245: A team's mailbox runs end to end: connected and tested in the console, bound through a review, a PDF read, checked and decided by a person, a case opened, the reply sent from the mailbox, a redelivery ignored |
| `usecases/agents-service/a-mixed-levy-email-is-read.md` | uc-246: A mixed court order email is read by kind in parallel: a case and a webhook per document, a person checks the doubtful read, and the sender gets a reply |
| `usecases/agents-service/a-hold-on-a-customer-s.md` | uc-248: A hold on a customer's account: matched, worked out, approved in time or by a supervisor after the deadline, placed, noted on a case, and the outside system told |
| `usecases/agents-service/a-complaint-email-is-triaged-attachments.md` | uc-249: A complaint email: each attachment recognised and its read kept, the complaint read and triaged by an agent, a case by urgency, a hold started, and an approved reply |
| `usecases/agents-service/a-case-reads-assembled.md` | uc-251: A case reads assembled: typed fields in its case type's order, what it waits on and the drafted action, its run, workflow and file; decided on the task page, the action reads decided |
| `usecases/agents-service/archive-a-workflow.md` | uc-252: A builder archives a workflow: it starts no run and leaves both lists, its run kept; restored, it serves its live version again |
| `usecases/agents-service/branches-join.md` | uc-400: A workflow's branches join before the next step, the step after the Join running once |
| `usecases/agents-service/step-output-shapes.md` | uc-401: A workflow's step outputs are known before it runs, and a misspelt mapping is warned |
| `usecases/agents-service/wait-for-children.md` | uc-402: A workflow waits for its children and uses their results |
| `usecases/agents-service/wait-and-reminders.md` | uc-403: A workflow waits for a time or date and reminds a person |
| `packages/usecase-runner/overview.md` | Use case runner: modules, verdict, exit codes, tests |
| `architecture/dependencies.md` | Every third-party Python package in the lock, and each service's, with version, licence, native code and network behaviour (generated by `make sbom`, checked by `make verify`) |
| `diagrams/README.md` | The architecture diagrams: one YAML data file each, the SVG exported from it for GitHub, and the data format the docs site draws them from |
| `architecture/make.md` | How make is organised: root orchestration, fragments by concern, the service verb set, env names, ports, `ISOLATED=1`, the daily commands |
| `architecture/embedded-chat.md` | Embedded chat for customers: the design, the identity options and the recommendation |
| `services/agents-service/overview.md` | Agents service: modules, graphs on four calls, settings, proofs, where it differs from the specs |
| `services/agents-service/chat-streaming.md` | Chat streaming: the SSE events, `replace`, and the audit record of a withdrawn answer |
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
| `services/agents-service/workflow-node-coverage.md` | Which seeded workflow runs each node type and which use-case check proves it (customer_hold uc-248, complaint_triage uc-249) |
| `services/kb-service/overview.md` | kb-service: knowledge bases with owners, file sources, sync into page and section passages, full-text retrieval, changes, and what is not built |
| `services/models-service/overview.md` | models-service: aliases, keys with budgets, admission and OpenAI-compatible egress with a metadata-only call log |
| `services/platform-service/overview.md` | platform-service: sign-in, sessions, members, invites, API keys and audit; the only token issuer, verified elsewhere through ops_identity |
| `services/tools-service/design.md` | tools-service design: the flow, the Connections screens as wireframes, the API, the data and the sequences |
| `services/documents-service/design.md` | documents-service design: the flow, six screens as wireframes, the API, the data, the sequences, the workflows that use it and the sample documents |
| `services/tools-service/overview.md` | tools-service: the tool-module registry, calls resolved and validated through it, executors, and the executions log |
| `services/files-service/overview.md` | files-service on :8750: uploads, proxy routes, dedupe, downloads, scan hook, retention and legal holds over local, S3 and Azure Blob stores; its client |
| `services/files-service/tests.md` | files-service failure modes and the test guarding each |
| `services/documents-service/overview.md` | documents-service on :8760: extractions, document types, samples and test runs, reading bytes through files-service; the sample documents as requirements |
| `packages/ops_ingest/overview.md` | Knowledge ingestion library: parsing, splitting, metadata, dedupe, source rules |
| `packages/ops_ingest/tests.md` | Knowledge ingestion failure modes and the test guarding each |
| `packages/ops_email/overview.md` | Email library: mail in and out behind two protocols, providers picked by settings |
| `packages/ops_email/test-with-gmail.md` | Steps to run the Email received trigger from a real Gmail mailbox with an app password |
| `packages/ops_signin/overview.md` | Sign-in library: password hashing, OIDC with PKCE, SAML, and a fake identity provider |
| `plan/implementation-plan.md` |
| `plan/ai-gateway-console.md` | AI gateway console feature: prior art, placement under Govern, pages, contract, open questions (plan only) |
| `plan/agent-completions-through-models-service.md` | Agent turns on their own alias through models-service: what exists, what changes, uc-028, decisions, slices (research note) |

File names are topics. Specs keep their number (01–17; 05 and 06 unused) and decision records their ADR id in the
title, so cross-references such as "spec 03 5.2" or "ADR-0005" still resolve.
