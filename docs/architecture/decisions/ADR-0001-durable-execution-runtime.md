# ADR-0001 Durable execution and workflow runtime

Status: accepted (draft for review). Formerly DR-1.

## Context

Every workflow in scope is a long-running, per-item process: one email becomes one case, which waits
for classification, drafted actions, one or more human approvals over hours or days, SLA timers and
escalations, and then executes approved actions against systems of record. The runtime must survive
process and node failures without losing or repeating a payment instruction, keep a step history
that auditors can read, let a new workflow version go live while yesterday's cases finish on the
version they started on, and run inside the bank. The bank has no incumbent runtime, so this is a
greenfield choice.

The product direction is to build on open source such as Temporal and n8n, so that existing
implementations can be brought in. This record tests that direction rather than assuming it, and
separates the two jobs it combines: the **execution system of record** (where a run's state lives and who
guarantees it completes) and the **connector catalogue** (how many systems we can reach without
writing an adapter).

## Options

| Option | What it is | Key facts (sourced) |
|---|---|---|
| **Temporal** | Durable execution engine; workflow code is replayed from an event history; activities do I/O | Server is MIT ([repo][temporal-repo]); latest server release listed is v1.32.0 ([releases][temporal-rel]). Timers are persisted and "a single Worker can await millions of Timers concurrently" ([timers][temporal-timers]). Worker Versioning is GA, with Pinned runs that "complete on a single Worker Deployment Version" and ramping ([versioning][temporal-wv]). Self-hosted persistence on PostgreSQL, MySQL or Cassandra; visibility on PostgreSQL, MySQL, SQLite, Elasticsearch or OpenSearch ([visibility][temporal-vis]). JWT authoriser, mTLS, OIDC on the UI, payload codecs; the default authoriser allows every request until configured ([security][temporal-sec]). Event history limit 51,200 events or 50 MB per run ([limits][temporal-limits]). |
| **n8n** | Visual workflow automation with a large connector catalogue | Sustainable Use License: use "only for your own internal business purposes", distribution only "free of charge for non-commercial purposes"; `.ee.` files under the n8n Enterprise License ([licence][n8n-lic]). 1,500+ integrations ([repo][n8n-repo]). SSO, Git environments, log streaming and external secrets are paid tiers ([pricing summary][n8n-ent], secondary source). Queue mode runs on Redis and Postgres; a run whose worker dies is marked crashed and restarts from the beginning rather than resuming mid-workflow (community answer, not n8n staff: [forum][n8n-crash]); an open n8n PR in October 2026 fixes crash data being overwritten by the stalled-job handler ([PR 40166][n8n-pr]). Wait node resumes by webhook; tool-level approval exists for AI agent tools ([HITL guides][n8n-hitl], secondary). Can expose workflows as an MCP server ([MCP trigger][n8n-mcp]). |
| **Camunda 8** | BPMN 2.0 engine (Zeebe) plus Operate, Tasklist, Optimize | Source under Camunda License v1; "To use the software in production, purchase the Camunda Self-Managed Enterprise Edition" ([licences][camunda-lic]). 8.8 adds an AI Agent connector looping over a BPMN ad-hoc sub-process, and an MCP client connector ([agentic][camunda-ai]). |
| **Apache Airflow 3** | Batch DAG scheduler | Apache 2.0. 3.1 added deferrable human-in-the-loop operators that "pause a DAG until a human validates" ([HITL][airflow-hitl]). |
| **Restate** | Durable execution via a log-based server and SDK handlers | BSL 1.1 with an additional use grant permitting internal production use; converts to Apache 2.0 four years after each release ([licence][restate-lic]); v1.7.13 released 2026-10-01 ([releases][restate-rel]); SDKs for TS, Java/Kotlin, Python, Go, Rust ([repo][restate-repo]). |
| **Inngest** | Event-driven durable functions | Server under SSPL with delayed Apache 2.0 publication; SDKs Apache 2.0; self-hosting supported ([repo][inngest-repo]). |
| **Hatchet** | Postgres-backed task orchestration with durable tasks | MIT; durable sleep and event waits; Python, TS, Go, Ruby SDKs ([repo][hatchet-repo]). |
| **Dapr Workflows** | Workflow building block on the Dapr sidecar | Durable timers and external events supported; only state stores that support workflows; docs fetched did not describe versioning of running workflows ([overview][dapr-wf]). |
| **AWS Step Functions** | Managed state machines | Callback tasks wait until the one-year execution quota ([callbacks][sfn-cb]). AWS-only. |
| **Azure Durable Functions / Durable Task Scheduler** | Managed durable orchestration | Scheduler is an Azure resource; the local emulator "isn't suitable for production use"; 1 MB payload limits ([DTS][azure-dts]). |
| **LangGraph with a checkpointer** | Agent graph library with persisted state per thread | Postgres and SQLite checkpointers; interrupts for human input; docs warn checkpoints accumulate ([persistence][lg-persist]). Temporal ships a LangGraph plugin in public preview that runs nodes as activities and maps `interrupt()` to signals ([plugin][temporal-lg]). |
| **Microsoft Agent Framework workflows** | Successor to Semantic Kernel and AutoGen; graph workflows with checkpoints | 1.0 on 2026-04-03, MIT, .NET and Python, workflows with checkpointing and human approval ([MAF 1.0][maf-10]). Resume needs an explicit checkpoint id and nothing restarts a crashed workflow automatically (argument by Diagrid, a Dapr vendor, so weigh accordingly: [Diagrid][maf-diagrid]). |
| **Build our own on Postgres and a queue** | A job queue such as BullMQ on Redis with our own state tables | An earlier internal product built this way lost jobs to stale workers on a shared Redis ([design lessons](../../specs/design-lessons.md), "Queues, jobs and durable execution"). |

### Scored comparison

Criteria and weights are defined in the [architecture overview](../overview.md#evaluation-criteria).

| Option | Durab. 13 | Determ. 8 | HITL 13 | Versioning 13 | Security 9 | On-prem 9 | Licence 9 | Talent 4 | Connectors 4 | Fit 4 | Marginal 14 | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Temporal (with our interpreter) | 5 | 5 | 5 | 5 | 4 | 4 | 4 | 4 | 2 | 5 | 4 | **4.43** |
| Camunda 8 | 5 | 4 | 5 | 4 | 4 | 3 | 2 | 3 | 4 | 4 | 4 | **3.95** |
| Azure Durable / DTS | 5 | 4 | 5 | 3 | 5 | 1 | 2 | 3 | 3 | 4 | 3 | **3.55** |
| Restate | 5 | 4 | 4 | 3 | 3 | 4 | 3 | 2 | 1 | 5 | 3 | **3.52** |
| AWS Step Functions | 5 | 4 | 4 | 3 | 5 | 1 | 2 | 4 | 4 | 4 | 3 | **3.50** |
| Dapr Workflows | 4 | 4 | 4 | 2 | 4 | 3 | 5 | 2 | 3 | 4 | 3 | **3.48** |
| Hatchet | 4 | 4 | 4 | 2 | 3 | 4 | 4 | 2 | 1 | 4 | 3 | **3.31** |
| Inngest | 4 | 4 | 4 | 3 | 3 | 2 | 2 | 2 | 2 | 5 | 3 | **3.16** |
| Build own | 2 | 2 | 3 | 3 | 4 | 4 | 5 | 3 | 1 | 4 | 3 | **3.11** |
| n8n as execution core | 2 | 2 | 3 | 2 | 3 | 4 | 2 | 3 | 5 | 4 | 5 | **3.06** |
| LangGraph + checkpointer | 3 | 2 | 4 | 2 | 3 | 4 | 4 | 4 | 3 | 4 | 2 | **3.04** |
| Airflow 3 | 3 | 2 | 3 | 2 | 3 | 4 | 5 | 5 | 4 | 1 | 2 | **2.96** |
| Microsoft Agent Framework | 2 | 3 | 3 | 2 | 4 | 3 | 4 | 3 | 3 | 4 | 3 | **2.96** |

n8n scores highest on marginal effort, because building a workflow on its canvas is fast. That
speed does not carry the bank's controls (module scope with expiry, the gate, evidence per version),
which would still have to be built around it, and it does not lift n8n's durability and licence
scores. Temporal scores 4 rather than 5 because the marginal speed comes from our interpreter and
templates, which we have to build.

Scores are our judgement from the cited facts. Where a fact was not found (for example Camunda's
and Restate's handling of in-flight version migration, which we know of but did not re-read for this
draft), the score is marked by its row's evidence in the options table and is **unverified**.

### Why each runner-up loses

| Option | Main reason it is not chosen |
|---|---|
| Camunda 8 | Production use needs an enterprise licence, so the bank pays per environment for an engine it could run under MIT, and the AI agent loop must be expressed as a BPMN ad-hoc sub-process. It is the strongest alternative if the bank wants a commercially supported BPMN product (see counter-argument). |
| Azure Durable, Step Functions | Durable and well run, but they tie every workflow to one cloud's control plane. The problem statement requires operability on-prem or in private cloud, and moving off later means rewriting every orchestration. |
| Restate | Technically strong and simpler to run, but BSL 1.1 is source-available, the talent pool is small, and the bank's vendor-risk review is easier with an OSI licence. |
| Dapr Workflows | Apache 2.0 and portable, but the docs we read are silent on versioning of running workflows, which is the criterion this platform leans on hardest. |
| Hatchet, Inngest | Younger, smaller teams; Inngest's server licence is SSPL. Both are reasonable for SaaS products and weaker for a bank's vendor review. |
| LangGraph, Microsoft Agent Framework | Agent-graph libraries with checkpoints. Checkpointing saves state; it does not supervise, restart, de-duplicate or time out a run. Both remain useful **inside** an agent block (and the Temporal LangGraph plugin lets an existing LangGraph agent run durably). |
| Airflow | Built for scheduled batch DAGs. It now has deferrable human approval, but a run per email, thousands concurrent, with per-run SLA timers is outside its design. Keep it for the bank's data pipelines that feed knowledge modules. |
| Build own | This is the path that produced the silent job loss described in the design lessons. A durable timer, idempotent retry and version-pinned replay are a multi-quarter build with nothing visible to users. |
| n8n as the execution core | Three separate problems. A crashed run restarts from the beginning instead of resuming, so a side-effecting step can repeat. The licence allows the bank's own internal use but not a vendor shipping n8n inside a paid platform, and the governance features a bank needs (SSO, Git environments, log streaming, external secrets) are paid tiers. Version pinning of in-flight runs is not documented in what we read. |

## Decision

Temporal, self-hosted, is the execution system of record. One interpreter workflow type executes
every published definition. Temporal Cloud stays an option if the bank's cloud policy allows it; the
SDK is the same.

n8n can serve as a **connector source behind the data gateway** and holds no run state. If the bank
runs its own n8n instance for internal use, a module owner can publish an n8n workflow as a tool
module (n8n can serve workflows over MCP via its MCP Server Trigger, [docs][n8n-mcp]). The data
gateway then scopes, logs and approves calls to it like any other module. The run's durability and
history stay in Temporal. Two conditions apply: the bank's legal team confirms the Sustainable Use
License covers its use, and any vendor delivering the platform does not redistribute n8n.

The same pattern applies to other catalogues: MCP servers, OpenAPI-described services, and Apache
Camel routes if the bank already runs them (Camel is not assessed here; **unverified**).

### Phase-1 node types

The palette has 31 node types: the mock's 28 plus three platform nodes. Three of the six phase-1
types are configurations of existing nodes, so the canvas, inspector and schema gain only three
entries.

| Phase-1 type | Palette mapping | Kind |
|---|---|---|
| `classify_intent` | Node 9 "Classify and route", with the template's intents as its labelled paths and the confidence threshold as its condition | Configuration of an existing node |
| `extract_fields` | Node 10 "Extract", with the per-intent typed field contract (`01` 4.4) | Configuration of an existing node |
| `open_case` | New platform node P1 "Open case": creates the case, routes it to a queue and starts the SLA timer | New node (template only in phase 1) |
| `draft_action` | New platform node P2 "Draft actions": runs the drafting agent (node 7 "Agent") once per intent action and stores the full payload and citations; it has no side effects | New node (template only in phase 1) |
| `per_action_approval` | New platform node P3 "Approve each action": one decision task per drafted action, using the decision-task machinery of nodes 16 and 17 (approval gate, two-person approval), issuing human or policy approval tokens, then executing each approved action | New node (template only in phase 1) |
| `send_reply` | Node 26 "Send email", bound to operation `mail.send_reply` of module `m365-mail`; a `write` that runs only as an approved drafted action | Configuration of an existing node |

## Consequences

### Strongest counter-argument and our answer

**"Banks know BPMN. Camunda gives Risk and Audit a diagram they can read that is also the thing that
executes, plus a vendor with an SLA. Temporal asks every author to write deterministic code."**

| Point | Answer |
|---|---|
| Auditors read BPMN | Our authors never write Temporal code. The executable artefact is the JSON definition, rendered as the canvas. We can export a BPMN view of any version for reviewers who want one (ADR-0003), and the run history is shown on the same graph. |
| Determinism is hard | True for application teams writing workflows by hand. Here only the interpreter is workflow code, owned by the platform team and covered by replay tests against recorded histories. |
| Vendor support | Temporal Technologies sells support and Temporal Cloud; the MIT licence means the bank can keep running and patching the server if that relationship ends. Camunda's production licence makes the vendor relationship mandatory. |
| Agentic features | Camunda 8.8 added AI agent and MCP connectors. Our agent blocks sit in activities and call models through the AI gateway, so engine-level AI features add little. |

### What would change this decision

- The bank's procurement or Model Risk function requires a commercially licensed BPMN engine as the
  record of execution. Then Camunda 8 Enterprise, and the interpreter becomes a BPMN compiler.
- A cloud-only mandate on Azure or AWS with no on-prem requirement. Then the managed engines' lower
  operating cost could outweigh portability; the interpreter design limits the rewrite.
- Temporal relicenses the server away from MIT, or the self-hosted server falls materially behind
  Temporal Cloud in features the platform needs.
- Measured operating cost of a self-hosted Temporal cluster at the bank's volume exceeds what the
  platform team can staff ([open question 3](../overview.md#open-questions)).

## Phase 1 vs later

| Phase 1 (first email workflow) | Later |
|---|---|
| Temporal clusters for non-production (`dev`, `test`) and production, PostgreSQL persistence | OpenSearch visibility if search over runs needs it |
| Interpreter with the node types the email template uses: email trigger, agent block, knowledge query, tool call, condition, `classify_intent`, `extract_fields`, `open_case`, `draft_action`, `per_action_approval` with SLA timer, `send_reply`, error path, end (mapped onto the palette in [Phase-1 node types](#phase-1-node-types)) | Canvas-only node types (loops, parallel fan-out, sub-workflow), continue-as-new upgrade path for long cases |
| Worker Versioning with Pinned runs from the first release, because retrofitting it means draining every open case | Worker Controller automation, ramp policies |
| No n8n | n8n or other catalogues as tool modules, per [open question 11](../overview.md#open-questions) |

## Sources

[airflow-hitl]: https://airflow.apache.org/docs/apache-airflow/stable/tutorial/hitl.html
[azure-dts]: https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-task-scheduler/durable-task-scheduler
[camunda-ai]: https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-subprocess/
[camunda-lic]: https://docs.camunda.io/docs/reference/licenses/
[dapr-wf]: https://docs.dapr.io/developing-applications/building-blocks/workflow/workflow-overview/
[hatchet-repo]: https://github.com/hatchet-dev/hatchet
[inngest-repo]: https://github.com/inngest/inngest
[lg-persist]: https://docs.langchain.com/oss/python/langgraph/persistence
[maf-10]: https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/
[maf-diagrid]: https://www.diagrid.io/blog/still-not-durable-how-microsoft-agent-framework-and-strands-agents-repeat-the-same-mistake
[n8n-crash]: https://community.n8n.io/t/n8n-queue-mode-what-happens-to-a-job-when-a-worker-crashes-or-restarts/314416
[n8n-ent]: https://pipeline.zoominfo.com/sales/n8n-features
[n8n-hitl]: https://humangent.io/blog/n8n-human-in-the-loop-guide
[n8n-lic]: https://docs.n8n.io/n8n-community-license
[n8n-mcp]: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger
[n8n-pr]: https://github.com/n8n-io/n8n/pull/40166
[n8n-repo]: https://github.com/n8n-io/n8n
[restate-lic]: https://raw.githubusercontent.com/restatedev/restate/main/LICENSE
[restate-rel]: https://github.com/restatedev/restate/releases
[restate-repo]: https://github.com/restatedev/restate
[sfn-cb]: https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
[temporal-lg]: https://docs.temporal.io/develop/python/integrations/langgraph
[temporal-limits]: https://docs.temporal.io/cloud/limits
[temporal-rel]: https://github.com/temporalio/temporal/releases/latest
[temporal-repo]: https://github.com/temporalio/temporal
[temporal-sec]: https://docs.temporal.io/self-hosted-guide/security
[temporal-timers]: https://docs.temporal.io/workflow-execution/timers-delays
[temporal-vis]: https://docs.temporal.io/self-hosted-guide/visibility
[temporal-wv]: https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning
