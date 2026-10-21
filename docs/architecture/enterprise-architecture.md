# Ops AI architecture

Status: current. The platform with what an enterprise runs around it: identity, observability, secrets, both gateways, dependencies, and how it is built and deployed.

Ops AI is an open-source platform that lets an enterprise's operations teams hand routine work to AI, with a person approving anything that moves money or changes a record. It runs work in two ways: agents, which decide their next step within set limits, and workflows, which run the same typed steps every time. A deployment can run either or both. All work reaches business systems and AI models only through two gateways, and stores its state in a SQL database the enterprise provides.

Ops AI is pre-release. Each part carries a status label for what is in code today.

- **built**: in code, end-to-end checks pass
- **partial**: part of it is in code
- **planned**: designed, build scheduled
- **dependency**: outside the platform: the enterprise runs it, the platform connects to it

![Ops AI architecture: identity, observability and secrets across the top; people and systems on the left; agents and workflows side by side above the shared services; every tool call through the data gateway and every model call through the AI gateway; the database and object storage below; the build-to-deploy lane along the bottom](../diagrams/enterprise-architecture.svg)

*Each numbered dot matches the numbered section below that explains that part. Every tool call and every model call leaves the platform through the two gateways on the right.*

## Features

Ops AI is one platform. Its features fall into three groups: two ways of running work, agents and workflows; the services every run uses; and the two gateways that every outside call passes through. A deployment can run agents, workflows or both.

| Feature | What it gives an operations team | Status |
|---|---|---|
| [Agents](#5-agents) | An agent reads a request, chooses what to look up and drafts a reply or an action, within the limits it was published with | partial |
| [Workflows](#6-workflows) | A graph of typed steps that runs the same way every time and records each step in a journal | partial engine built |
| [Chat and console](#4-chat-and-ui) | A web console for people, chat with an agent, and channels that start runs from email or an API | partial |
| [Reviews and cases](#7-shared-services) | One queue where a person approves, rejects or edits what an agent or a workflow proposes | built |
| [Triggers and timers](#7-shared-services) | Start work from a request, a schedule or an event, and act when a deadline passes | partial |
| [Knowledge and files](#7-shared-services) | Searchable knowledge bases with cited answers, and document storage with retention and legal hold | partial knowledge and file storage with its settings page built; retention jobs and large-file upload planned |
| [Work feed](#7-shared-services) | One list of all work in progress, agent and workflow alike | planned |
| [Access control](#1-access-control) | Sign-in, teams, roles, API keys and an audit log | partial |
| [Data gateway](#8-data-gateway) | The single, policy-checked path to business systems, over REST or MCP | built |
| [AI gateway](#9-ai-gateway) | The single path to AI models, with keys, budgets and a call log | partial |

### Agents and workflows: when to use which

|   | Agent | Workflow |
|---|---|---|
| Who decides the steps | The agent, inside the limits it was published with | The workflow definition: the same steps every time |
| Core primitive | The agent run API | The workflow run on the workflow engine |
| Built on top | Chat, agent jobs, agents calling agents | Workflows of typed nodes, triggers, human review steps |
| Shape | An agent platform: configured agents that people chat with and that run jobs | A workflow engine: a visual graph of steps with triggers and a journal of every run |
| Suited to | Work that needs judgement: reading a messy request, choosing what to look up, drafting a reply | Work that must be repeatable and auditable step by step: a dispute, a court order, a hold on a payment |

<!-- site: cards -->
- **Agents inside workflows, workflows as agent tools**: A workflow step that needs judgement starts an agent run and receives its output in a declared schema. An agent can call a published workflow as a tool, found by search and available only when granted. Both links work today through adapters inside agents-service. Moving each onto the public run APIs is planned, so that a deployment with only agents, or only workflows, runs on its own.
- **Services every run uses**: Identity and teams, reviews and cases, triggers and timers, knowledge, files and the work feed serve agents and workflows alike. Every write passes the data gateway with its approval policy and fails closed.

> [!NOTE]
> **Why agents and workflows run separately.** Agents and workflows fail in different ways and are reviewed in different ways: an agent is judged on its answers, a workflow on its steps. Separate run APIs let each be tested, approved and deployed on its own, and a fault in one stays inside its own data. The cost is maintaining the two links between them, which is smaller than tying every agent change to the workflow engine.

## 5 Agents

An agent is an instruction, a model alias and its attachments: tools, knowledge, skills, guardrails and a budget. It is versioned, goes live through a publish review, and decides its own next step inside those limits. Every way of using an agent, from a chat message to a scheduled job, is a run on one agent run API.

| Part | What it does | Status |
|---|---|---|
| Agent builder | Create an agent, version it, publish it through a review by a second person | built |
| Publish policy | An administrator chooses which publishes need a second person's review | planned in development |
| Agent run API | One run resource with stream, wait and background modes. Chat, jobs, agent tests and the workflow agent step all call it | partial runs exist inside chat threads; the public run resource is next |
| Kernel | Runs one turn: builds the prompt, calls the model, runs tools, checks the answer. Capabilities plug in as packs on one contract | built pack contract planned |
| Tools | Granted operations through the data gateway; a write waits for approval and, where policy asks, step-up sign-in | built |
| Knowledge | Searches granted knowledge bases; answers cite page and section | built |
| Skills | Versioned procedures loaded when a request matches, plus always-on skills, with caps | built |
| Guardrails | Blocked topics checked on the question and the answer, failing closed. A builder can switch a pinned guardrail off for a version, and the publish review names the change. Required citations, output shape and personal-data redaction follow | partial |
| Budgets | Model calls, tool calls, cost and deadline counted, with the stop reason shown. Built: per turn, where an empty tool-call cap means no cap and an empty model-call cap means 50, and per chat conversation, where an empty cap means 200 model calls and a cost of 5.00. Per job and per team are planned | partial per turn and per conversation today |
| Agent jobs | A trigger or schedule plus a goal: the agent works over many turns, pauses for people and ends with a report. Live only after a publish review; default budget 10 turns, 20 tool calls, US$0.50 and 24 hours | planned |
| Evals | Scenario suites and a release gate on their results before a version is published | planned designed in the console on mock data |
| Agents calling agents, memory | Sub-tasks handed to another agent through the run API; memory read and written under policy | planned |

<!-- site: cards -->
- **What a caller may change per run**: The published agent sets defaults and limits. A caller or the chat UI may: choose a model from the agent's allowed list, and a temperature within its range; add to the instructions; narrow the tools, and choose or narrow the knowledge; lower the budget. A request outside those limits is refused with an error that names the limit, so a run always uses exactly the settings it asked for. Guardrails and approvals stay exactly as published. Each run records the settings it used. Chat applies this today through a settings panel on each thread; the run API that gives other callers the same controls is planned.
- **One run API for every caller**: Chat sends one run per message on a thread. A job is a background run with a goal. An agent test and the workflow agent step are runs with a fixed input and an output schema.

## 6 Workflows

A workflow is a graph of typed nodes that runs the same steps every time. Each step is recorded in a journal: after a crash the run resumes from the journal, and every write is reconciled by its key, so a payment is sent once. Workflow definitions are data, so authors compose them in the editor and write no engine code.

<!-- site: cards -->
- **Engine core**: Flow control, human review steps, the step journal, the work queue, workers, leases with generation fencing, and reconcile-by-key for writes. LangGraph is the runner underneath.
- **Node types and the Node SDK**: A node type owns every fact about a step: ports, parameters, effects class, retry and executor. The editor, the validator and the runner all read the same registry entry. Seven types ship today (request trigger, set data, if, tool action, agent, human review, end) from a catalogue of 24 (22 steps and 2 attachments). Schedule, email, chat, webhook and poll start runs as triggers. The SDK for writing new ones is planned.
- **Node packs**: Node types ship in packs: ai, tools, files, agents and channels. Packs are installed at deploy time from an allowlist pinned by hash, and each journal row records the hash of the code that ran it.
- **Triggers**: Triggers are adapters on one start API, each with a dedupe key and window. Request triggers are built; email, chat, schedule, event and poll triggers follow.

| Capability | What it does | Status |
|---|---|---|
| Editor and run detail | Draw a workflow from the server's node types; see each step's input, output, attempts and errors, and the result of the End step | built |
| Human steps | A review step whose options are output ports; ask the customer; hand off | partial review built |
| Data mapping | Values move between steps by path lookups; transforms run in a dedicated JMESPath node | partial |
| Forms | Every node setting is a form generated from the type's schema, with an optional custom form per type | partial generated forms built for the seven shipped types; custom forms planned |
| Lifecycle | A saved version is a draft. Publishing opens a review; approval makes it live and retires the previous live version. A workflow can be paused and resumed, and a run can be cancelled: the step in progress finishes and is recorded first. A run keeps the version it started on; migrating paused runs is planned | partial publish, pause and cancel built |
| Error handling | Error ports on every type that can fail, an error path per workflow, a stop with a reason | partial |
| Test and repair, sub-workflows, templates | Test runs, pinned steps, retry from a node; start another workflow; a library of common processes | planned |

> [!NOTE]
> **Why mappings use path lookups.** A field that evaluated code would let every workflow author run code on the server. Path lookups cover most mappings, and the few that need a transform use a node built for it, which is reviewed like any other step.

## 4 Chat and UI

People reach Ops AI through the console, and systems and customers reach it through channels. Every surface starts runs through the same public APIs that the SDK uses.

<!-- site: cards -->
- **Console**: A Next.js app with sections for agents, workflows, chat, cases, reviews, knowledge, tools, access and audit. Every screen reads through one API contract, so the same build runs on an in-memory mock or on the services. The console calls each service directly at its own URL, signed in through platform-service. On services today: chat, agents, skills, guardrails and widgets, workflows, reviews, tools, secrets, the egress allow list, the tool call log, knowledge and storage settings, the Files page (which lists, searches, filters, downloads, deletes in bulk and places holds on files-service when its address is set, and hides setting retention and exporting evidence until the service offers them) and, with real sign-in, members, access and the audit log. On mock data: assurance and evals, model risk, prompt blocks, integrations, deployments and Cases; a page that still shows sample data carries a Preview mark while real services answer beside it.
- **Chat**: A thread of runs on one agent, one run per message. Answers stream with citations, tables and charts, and a drafted action appears as an approval card in the thread. A banker can attach a file to a message (PDF, text, Markdown, CSV or Word, up to 10 MB) and, within the agent's limits, choose the model, temperature, tools and knowledge for a thread. An agent can show a table, chart or form from a widget template that a builder published through a review. When a conversation uses up its budget, the chat shows a card instead of an error: the person who started it can continue, and an admin of its team can raise the cap.
- **Channels**: A channel is a trigger: it turns what arrives into a run on a published version. The REST API and the shared mailbox start runs today; the mailbox runs on a test mail source, and a real mail tenant is next. An agent's chat can be embedded on an intranet page: a team creates a widget deployment that pins one published version of the agent and lists the exact page origins allowed to use it, and the page loads one script tag. An MCP endpoint that offers agents to AI clients is planned. The page never holds a long-lived key. It gets a session that lasts 15 minutes and works only for that deployment, that origin and that person. The session comes from the bank's single sign-on token, or from the bank's own server with a team API key. Messages are limited to 60 a minute per deployment and 10 per person; today the count is kept inside one process.
- **One work list**: Agents and workflows publish the same work-item contract, so Cases, Reviews and Overview list agent jobs and workflow runs together, already joined by the API.

## 1 Access control

Every request passes the same checks in order. Access is granted per team, and a person can hold a different role in each team they belong to. `platform-service` is the only issuer of identity tokens; every other service verifies them locally against a published key set.

<!-- site: steps -->

1. **Authentication**A short-lived token from `platform-service`, or a team API key. Federation with an enterprise IdP (Entra ID, Okta, Keycloak) over OIDC is planned.
2. **Tenant isolation**Each tenant sees only its own records; a request for another tenant's record returns 404, which keeps its existence private. Row-level security protects run, checkpoint, workflow and identity tables; the data gateway and knowledge filter by tenant in each query.
3. **Team scoping**The token lists the caller's teams. A record in another team of the same tenant answers 403 and names the owning team.
4. **Authorization (RBAC)**One role per team, from the table below. API keys are `read` or `write`; a read key is limited to reads.
5. **Policy and approval**A write to a system of record also needs an approval token for that exact input, checked by OPA at the data gateway.

| Role | May | Enforced today |
|---|---|---|
| `admin` | Manage members, invites, API keys and access for the team; read the audit log. An admin of the Security team also manages tool secrets, the egress allow list and storage settings | built (yes) in platform-service, kb-service and for the Security team's settings |
| `builder` | Edit agents, workflows, skills, guardrails, widgets, knowledge and tool modules; create, pause and poll channel deployments; request a publish | built (yes) every write to these in agents, knowledge and tools needs a builder or admin of the owning team; a channel deployment belongs to a team, and a builder of another team is refused |
| `approver` (shown as reviewer in the console) | Decide reviews and drafted actions. Approval always comes from someone other than the requester | partial (partly) approvals come from a second person; a tool module review needs the security team's approver or admin |
| `viewer` | Read everything in the team | partial (partly) refused on every definition write; starting runs, chatting and deciding reviews do not check the role yet |
| API key | Act for one team with `read` or `write` scope | built (yes) in every service, from the HTTP method |

A refused write answers 403 with the code `role_required` and names the role it needs; a builder acting in another team's records gets 403 `team_forbidden` naming the owning team. Mapping IdP groups to these roles, and platform roles such as model risk and security held through IdP groups, are planned.

> [!NOTE]
> **Why services verify tokens themselves.** Each call is authorized in the service that receives it, locally. Identity can restart or slow down without stopping work in progress, and token minting stays with `platform-service`, the only holder of the signing key.

## 8 Data gateway

`tools-service` is the only way an agent or a workflow reads from or writes to a business system. Each system is a tool module: imported from an OpenAPI description or an MCP server, reviewed by the security team, then published.

<!-- site: cards -->
- **Connections**: REST APIs, from an OpenAPI description. MCP servers, through the gateway's MCP client over streamable HTTP: tools are discovered with `tools/list` and called with `tools/call`. MCP servers are reached over HTTP only. Credentials are stored encrypted and stay in the gateway; agents and workflows receive results, with masked fields redacted. Agents and workflow tool steps call the gateway over HTTP with a service token. An MCP server that offers platform tools to outside clients is planned.
- **Controls on every call**: An approval policy per operation, with step-up sign-in where the policy asks for it. Rate and amount limits held in the database, so they apply across every gateway process. The security team's approver or admin reviews each module before it is published. A write carries an approval token bound to its input hash and the run's lease generation; OPA accepts it once, for that input, from the current run. Calls reach only allow-listed hosts at checked addresses. Every call is logged with its verified caller and reconciled by key. Each secret lists the operations that read it, can be limited to chosen teams, and cannot be deleted while an operation uses it. A call from a team the secret does not allow is refused before anything is sent.
- **Tool workbench**: A builder opens one operation on its own page, edits the call and its input, and runs it against the mock or the test environment. A draft mock response and a draft response transform are tried without being saved, so agents keep calling the published version until the change goes through review. A secret can be typed for a single run; it is not stored, logged or returned, and the request shown has it masked. The page lists the gateway's steps in order.

> [!NOTE]
> **Why two egress gateways.** A tool call acts on a system of record and needs an approval per call; a model call spends budget and needs a key per identity. Giving each its own gateway keeps business-system credentials and model-provider keys in separate processes, so a risk review can examine each path alone, and agent workers hold neither.

## 9 AI gateway

`models-service` is the way agents and workflows reach an AI model. Workers hold a gateway key; provider credentials stay in the gateway. Today agents use it once `OPS_MODELS_URL` is set, and it is started with `make -C services/models-service run`; making it the default path for every agent call is next.

| Part | What it does | Status |
|---|---|---|
| Aliases and connections | Versioned aliases such as `gpt-5.5` map to provider connections. Pointing an alias at Azure OpenAI, Anthropic, Bedrock or a self-hosted model is a connection setting | built OpenAI-compatible |
| Keys, budgets and admission | Gateway keys with rotation and a budget per key, checked before a run starts | built |
| Completions | An OpenAI-compatible completions endpoint | built |
| Call log | Metadata for every call: alias, key, tokens, cost, latency | built |
| Default path | Every agent and workflow model call routed through the gateway | partial opt-in today |
| Data plane and failover | Portkey OSS behind the gateway, with a second provider per alias | planned |

> [!NOTE]
> **Why model access goes through a gateway.** Changing provider, adding a self-hosted model or capping a team's spend is then a setting in one place, and every model call is metered and logged the same way whichever agent or workflow made it.

## 7 Shared services

Services that agents and workflows both use. Each is a package with its own API, so a deployment with only agents, or only workflows, keeps every one of them.

<!-- site: cards -->
- **Identity and teams**: `platform-service`: sign-in, sessions, tenants, teams, roles, invites, API keys and the audit log. A new person accepts an invitation through its link and is signed in. A person who already has an account accepts only while signed in as themselves, and the check runs inside the same database transaction as the acceptance, so an account created a moment earlier is still found. Team ownership on every entity is being completed.
- **Reviews and cases**: One review contract any producer opens and resumes by key, and one queue for people. A decision mints an approval token for the exact input and resumes the waiting run once. Served by agents-service today; moving into its own package, `ops_hitl`.
- **Triggers and timers**: One registry that starts an agent job or a workflow run, plus SLA timers that fire each outcome once. Moving into its own package, `ops_triggers`.
- **Knowledge**: `kb-service`: knowledge bases, their sources and passages cited by page and section. Deleting a base leaves a record, so an agent that cited it keeps its other bases.
- **Files**: `files-service` (port 8750) stores file bytes. An admin on the Security team chooses where each kind of file goes (a local folder, S3 or Azure Blob), under which credential and limits. Every new or changed target is tested with a small write, read and delete before the setting is saved, and credentials are sealed and never shown again. The service checks size, type and digest, keeps one stored copy per team for identical content, keeps versions, blocks deletion while a file is in use, and applies legal holds. A retried upload returns the first file. The file list answers search, an upload-date range, filters on purpose, scan result and sensitivity, and a count for each view (quarantined, under legal hold, unused for 30 days, expiring within 30 days) from the database query. A file that is used, held or still retained says why it cannot be deleted, and a bulk delete skips each such file and names the reason. The S3 target is tested against a mock S3 service and the Azure Blob adapter against an Azure emulator when one is running; no real cloud account has been used yet. Retention jobs, resumable large uploads, the console upload component and virus scanning (off for now) are planned. The knowledge service stores its uploads through it.
- **Work feed and audit**: One work-item contract that agents and workflows both publish, and one view of who did what across tool calls, model calls and decisions.

## Runs

A run is one piece of work by an agent or a workflow, with a status, a budget and an event stream. Workflow runs use these states today; agent runs adopt them with the run API (planned).

| State | Meaning |
|---|---|
| `queued` | Accepted and waiting for a worker |
| `running` | A process holds the run's lease and is executing it |
| `waiting` | Paused for a person, a timer or another run; the reason says which |
| `succeeded`, `failed`, `cancelled` | Finished, with a reason recorded for each failure or cancellation |

<!-- site: cards -->
- **A pause waits in place**: A run that needs a person moves to `waiting`, releases its lease and keeps its checkpoint. The decision resumes the same run. Waiting runs are kept for up to seven days.
- **Durable by default**: Each step is checkpointed. A running run holds a lease; if its process stops, a sweeper in another process takes the expired lease, raises the generation and continues from the last checkpoint. In testing, recovery started about 5.5 seconds after a process was killed.
- **Versions are pinned**: Definitions are immutable and identified by version and digest. A run keeps the version it started on through every later publish, and an operator can migrate a waiting run deliberately.

## Service map

A service is a package with API routes, background loops and its own database migrations. Each is named after the console section it serves. Today each service runs as its own process; a single host program, `ops-host`, that starts any set of them in one process is the first part of version 1.

| Service | Serves | Owns | Port | Status |
|---|---|---|---|---|
| `platform-service` | Access, Audit log, Settings | Sign-in, sessions, tenants, teams, roles, invites, API keys, audit; sole issuer of identity tokens | 8710 | partial |
| `agents-service` | Agents, Chat, Skills, Assurance | Agent definitions, versions, evals, publish review, runs, threads, budgets, channels, widget deployments | 8700 | partial |
| workflows (`ops_engine`) | Workflows | Node registry, definitions, runner, journal, work queue. Routes are served by agents-service today | 8700 | built |
| `tools-service` | Tools, Connections | Data gateway: tool modules, credentials, OPA policy, approval tokens, limits, call log | 8720 | built |
| `models-service` | AI gateway | Aliases, provider connections, keys, budgets, call log | 8730 | partial |
| `kb-service` | Knowledge bases | Sources, ingestion, retrieval, citations | 8740 | built |
| `files-service` | Files | File metadata, bytes, versions, references, legal hold, storage settings and credentials | 8750 | partial |
| `documents-service` | Document types; file Preview and Extract | Page layout, classify and split, extractions with cited positions, document types, templates, corrections and accuracy; reads bytes through files-service and never stores them | planned | partial |
| reviews (`ops_hitl`) | Cases, Reviews | Reviews, cases, queues, decisions, approval tokens | in agents | partial package planned |
| triggers (`ops_triggers`) | Deployments | Trigger registry, dedupe, schedules, SLA timers | in agents | partial package planned |

<!-- site: cards -->
- **Each service owns its data**: Every service has its own tables and migration chain and reads only its own. Services exchange data through their APIs, and each call between services is signed with the caller's own key.
- **Imports run one way**: Shared packages come first, then the workflow engine, then each service's activities, graphs, stores and API. The commit gate checks that order on every commit and keeps the workflow engine independent of the agent runtime. Services are moving to a domain, use case, adapter and API layout.

| Package | What it does | Used by |
|---|---|---|
| `ops_identity` | Verifies identity and service tokens locally and enforces API key scope | every service |
| `ops_service_kit` | Settings (the one place configuration is read), errors, ids, logging | every service |
| `ops_agent_kernel` | One agent turn with tools, knowledge, skills, guardrails and token usage | agents |
| `ops_engine` | Workflow node registry, validation, compiler to LangGraph, step journal, work queue, workers | workflows |
| `ops_checkpointer` | Run checkpoints with tenant isolation | agents, workflows |
| `ops_store` | The store seam: each repository declares the guarantees it needs from the database, with a conformance suite per backend | agents |
| `ops_policy` | Canonical input hash, approval and step-up token signing and verification | agents, tools |
| `ops_metering` | Usage, prices, cost and budget checks | agents, models |
| `ops_storage`, `ops_ingest` | Object storage on disk, S3 or Azure Blob; parsing, splitting and dedupe for knowledge | files, knowledge |
| `ops_files_client` | A typed client for files-service, so no service imports its code | knowledge |

## 10 Database

The platform connects to a SQL database the enterprise runs, usually a managed instance owned by its data team. Each service may have its own database or share a server. Development uses a local PostgreSQL 17 container, and unit tests use SQLite. Every table, its owning service, keys and status are on the [data model page](data-model.md).

| Database | Status | Tenant isolation |
|---|---|---|
| PostgreSQL (Azure Database for PostgreSQL, Amazon RDS or Aurora, Cloud SQL, self-run) | built (runs today) | Today: row-level security on run, checkpoint, workflow, chat attachment, chat search, widget deployment and identity tables, and a tenant filter in each query elsewhere. Planned: the store layer on every table, with row-level security as a backstop |
| Azure SQL (SQL Server dialect) | planned | Store layer, plus a security policy as a backstop, on from the first release |
| MySQL 8 | planned | Store layer |

- All three run through SQLAlchemy, with a CI job per database once each lands.
- Planned: every tenant query goes through scoped repositories that add the tenant filter, with a test that checks the filter is present.
- Backups, high availability, encryption at rest and network rules follow the enterprise's existing database practice.
- Services connect as a least-privilege login role. One platform migration needs a superuser or membership of `ops_platform_lookup`, so a managed PostgreSQL needs that grant before the first migrate.

> [!NOTE]
> **Why three databases.** Banks standardise on one of a small set of database engines, and adding a new engine to a bank's estate takes months of approval. Supporting PostgreSQL, Azure SQL and MySQL means Ops AI runs on the engine already approved. Putting tenant isolation in the store layer is what makes that possible, because row-level security exists on only some of them.

## 11 Build

One repository holds the console, every service and every shared library, with one toolchain per language and one gate that every commit passes. Each part is laid out so it can later move to its own repository with its names intact.

| Path | Holds | Stack |
|---|---|---|
| `apps/console` | The operations console. Reads every screen through one API contract | Next.js, TypeScript, shadcn/ui |
| `services/<x>-service` | One deployable per console section, each with its own `Makefile`, migrations, OpenAPI file and tests | Python 3.12, FastAPI, Alembic |
| `packages/ops_*` | Libraries used by two or more services, including the workflow engine and the agent kernel | Python 3.12, SQLAlchemy |
| `packages/usecase-runner` | Runs the end-to-end use cases and reports a verdict per check | Node, Playwright |
| `deploy/` | Deployment targets: Compose today; VM and Kubernetes scheduled | Compose, systemd, Kustomize |
| `docs/` | Architecture, decision records, one spec per topic, use cases, service docs | Markdown, checked on commit |

> [!NOTE]
> **Why one repository.** A change that crosses the console, a service and a library lands as one reviewed commit, checked by one gate. Contracts between parts stay in step.

### How a feature is built

A feature moves from the inside out, and each step has a fixed home. The console contract is the source of truth for the API.

<!-- site: steps -->

1. **Spec and use case**The behaviour, its failure modes and the end-to-end check that proves it.
2. **Type and contract**The data type and the method on the area's API contract in the console.
3. **Mock and hook**The mock implements the contract with fixtures; a hook gives screens the data. The screen works before the service exists.
4. **Service**Domain rules, then the use case and its ports, then adapters, then the API route, with a migration if a table changes.
5. **HTTP client**The console's HTTP client calls the new route, and the area moves from the mock to the service with a setting.
6. **Prove it**The commit gate passes and the use case passes end to end on the scripted model.

### The commit gate

| Check | What it covers |
|---|---|
| Console | TypeScript type check, the standards check (layer order, fixtures only in the mock), and every changed screen rendered in loading, error and empty states |
| Python | ruff and strict pyright across every package and service |
| Tests | Each service's pytest suite, on SQLite or PostgreSQL, with a scripted model in place of a paid one |
| Standards | Imports run in one direction, configuration is read in one place, fixtures live only under tests, every route is authenticated, and the workflow engine stays independent of the agent runtime |
| Docs | Every doc has a status line, sits in the folder that matches the code, and is listed in the docs index |
| Scope | The gates run on the content being committed, not on the whole working copy, so one person's unfinished file never blocks another person's commit |

> [!NOTE]
> **Why a scripted model in tests.** Tests give the same answer on every run and are free to run, so they run on every commit. Real model calls run only when approved, with a cap per experiment.

## Develop

Everything runs from the root `Makefile`. Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20 or later with pnpm 10, and Docker for the development PostgreSQL and OPA. A model key (`OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` for a `claude-*` alias) is needed only for real chat; every service starts without one and reports it on `/health`.

> [!NOTE]
> **Why a Makefile.** One entry point for install, verify, run and deploy, the same on a laptop and in CI. A new engineer runs the same three commands as the build server, and each service answers the same set of verbs.

<!-- site: cards -->
- **Console only**: Runs on in-memory data alone. Suited to screen work and demos. `pnpm install` then `make dev`, at `localhost:3016`. State lives in memory and resets on reload. `?mock=slow`, `?mock=error` and `?mock=empty` show each loading, error and empty state.
- **Full stack**: The console on the real services, with the model key supplied by the environment or a gitignored `.env`. `make install` once per clone: pnpm packages and one uv workspace for every Python service. `make up` starts PostgreSQL :5477, OPA :8181, platform :8710, agents :8700, tools :8720, kb :8740, files :8750 and the console :3016, applying each service's migrations to the existing database first, never dropping it (the files service starts before the knowledge service, which stores its uploads through it). If the database holds a migration this checkout does not have, `make up` stops and names the service. `OPS_STACK_WORKER=1` also starts the workflow worker, which runs workflows of typed nodes; `make -C services/models-service run` starts the AI gateway on :8730. `make up AUTH=platform` uses real sign-in through platform-service with seeded people.

| Daily task | Command |
|---|---|
| See what is running, on which port, started by whom | `make health` |
| Follow one service's log | `make logs SVC=agents` |
| Restart after a change (migrates first) | `make restart SVC=tools` |
| Open the database | `make db-shell` |
| Wipe the database and rebuild it empty (asks first on a shared stack) | `make reset-db` |
| Run a second, separate stack beside the first | `make up ISOLATED=1` (every port +1000, own database) |
| Stop | `make down` (`KEEP_DB=1` leaves the database running) |

### Testing

| Level | What it proves | Command |
|---|---|---|
| Unit and service tests | Domain rules and routes, mostly on SQLite with a scripted model | `make -C services/agents-service verify` |
| Integration tests | Checkpoints, leases, timers and the data gateway on real PostgreSQL | `make db-up`, `make migrate`, then the service's tests |
| Use cases | One user-visible behaviour end to end through the API or the console, on a database and ports the run owns | `make usecase-test UC=uc-010` |
| Real model calls | Behaviour against a live provider, approved per run | `APPROVED_REAL_CALLS=<n>`, capped at ten per experiment |

A use case passes only when its script exits 0, prints only `PASS` lines, at least one. Each names the check that fails when the behaviour breaks.

## Deploy

The same packages run in three layouts; only the host's flags change. Every release runs on one virtual machine with plain systemd, and Compose and Kubernetes are optional.

<!-- site: cards -->
- **One process**: Every service in one process. For evaluation, development and tests. Today `make up` runs each service as its own local process; the single-process host, `ops-host`, is the first part of version 1.
- **One virtual machine**: systemd units for a web process (all routes), a loops process (workers, sweepers, schedules, SLA timers) and separate `tools` and `models` processes, with PostgreSQL managed or on the VM, the OPA binary, and local disk or an object store.
- **Split services**: A Kustomize base per service and an overlay per environment, each service scaled on its own. Compose today covers the development PostgreSQL and OPA.

> [!NOTE]
> **Why three layouts.** One process is the fastest way to evaluate and develop. A single VM fits a small production deployment and bank estates that run plain virtual machines. Split services fit when load or a security boundary needs a component on its own. Because the code is identical in all three, a use case that passes in one passes in the others.

| Release step | What happens |
|---|---|
| Migrate | Run migrations once per release, before any new process starts; each service applies its own chain |
| Start beside the old | New processes start next to the old ones; workers claim only work stamped with their build |
| Drain and stop | Old processes stop once idle; runs in flight keep their pinned version, and waiting runs resume on the new build |
| Contract changes | Columns and tables are dropped one release later, so the previous build keeps working during the switch |

## Operations

Configuration comes from the process environment through one settings class per process. Every variable uses the `OPS_` prefix, plus the provider key names.

<!-- site: cards -->
- **Secrets**: The enterprise secrets manager (Vault, Azure Key Vault, AWS Secrets Manager) places values in the process environment. Tool credentials are read only by the data gateway, provider keys only by the AI gateway and storage credentials only by the files service. In test and production a service starts once its review key and secrets key are set.
- **Observability**: Services write structured events today (`model_call`, `unhandled_error`, timer events), and every run keeps a journal of its steps, owners and recoveries. Export through an OpenTelemetry collector to the enterprise APM, LangSmith or Langfuse is planned.

| Environment | `OPS_ENVIRONMENT` | What starts |
|---|---|---|
| Development | `dev` | Dev sign-in and default keys are available for local work |
| Test, production | `test`, `production` | Real sign-in only; a service starts once its review key and secrets key are set |

| Setting | Default | Effect |
|---|---|---|
| `OPS_DATABASE_URL` | dev container | The database a service connects to; its dialect selects the store renderers |
| `OPS_GATEWAY_URL` | unset | Set: write tools go through the data gateway. Production sets it |
| `OPS_MODELS_URL` | unset | Set: model calls and key budgets go through the AI gateway |
| `OPS_LEASE_TTL_SECONDS` | 15 | Time before another process takes over a stopped run |
| `OPS_SWEEP_INTERVAL_SECONDS` | 3 | How often each process checks for expired leases |
| `OPS_REVIEW_TOKEN_TTL_SECONDS` | 900 | Approval token lifetime |
| `OPS_TURN_DEADLINE_SECONDS` | 120 | Upper bound on one chat turn |
| `OPS_PRICES` | empty | Model prices per million tokens by alias, used for cost and budgets |

### Health and what to watch

| Signal | Why it matters | Healthy |
|---|---|---|
| `GET /health` per service | Process up; agents-service also reports database reachability and model key configuration | 200 from each |
| Expired leases taken over | The sweeper recovers stopped runs | Each within TTL plus one sweep interval |
| Crashed runs | A process stopped mid-step; recovery re-runs that step | Rare, each followed by a recovery run |
| Timers fired on time | SLA outcomes depend on them | Within one poll interval of due |
| Gateway calls settled | Every write reaches a final state | All rows complete |
| Checkpoint write p95 | Grows with state size and concurrency | Under 50 ms |
| Clock agreement | Leases and timers use the database clock | Skew well under the lease TTL |

### Runbooks

<!-- site: cards -->
- **Stuck run**: The run's state shows its status, next step, pending approval and SLA timers. Its journal shows each attempt's owner and generation. Running after its owner stops: the sweeper continues it after TTL plus one sweep. Waiting: it is with a person. Failed: fix the cause and resume from the last good checkpoint, or route it to people with a reason.
- **Bad version published**: Publish the previous definition again so new runs take it. Waiting runs can be migrated to a version where their waiting step exists. Running runs on the bad version can be routed to people in one call.
- **Key rotation**: Review key: set the new value on agents and tools, restart both, re-approve open reviews. Service keys: add the new public key beside the old one on every callee, restart, then retire the old key. Model keys and the database credential: change them in the secrets manager and restart.

## Integration points

Each row is a seam. Changing the choice changes a setting or an adapter, and the rest of the platform stays as it is.

| Seam | Default in the repository | Enterprise options | Status |
|---|---|---|---|
| Database | PostgreSQL in a local container | Managed or self-run PostgreSQL today; Azure SQL and MySQL 8 planned | dependency |
| Identity provider | platform-service with seeded people | Entra ID, Okta, Keycloak, any OIDC IdP | planned |
| Secrets | Gitignored `.env` locally | Vault, Azure Key Vault, AWS Secrets Manager, injected as environment | dependency |
| Model providers | Scripted model; OpenAI or Anthropic | Azure OpenAI, Anthropic, Bedrock, self-hosted, each behind an alias | partial |
| Business systems | Seeded tool catalogue | Core banking, CRM, ticketing, event streams, imported from OpenAPI or MCP | built |
| Object storage | Local filesystem | S3, Azure Blob, chosen per kind of file on the storage settings page (not yet tried on a real cloud account) | partial |
| Telemetry | Structured logs and the run journal | OpenTelemetry to an APM, LangSmith or Langfuse, a data lake | planned |
