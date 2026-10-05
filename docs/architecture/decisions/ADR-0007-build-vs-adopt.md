# ADR-0007 Build vs adopt

Status: accepted (draft for review). Formerly DR-7.

## Context

The platform needs an execution engine, two gateways, a registry and release gate, cases, evals,
identity and chat. Each can be adopted from an existing product or built. The problem statement's
test: adopt where the capability is the same for every bank; build thin where it depends
on the bank's systems, entitlements, policies or risk tiers.

## Decision

Adopt the engine, the gateways' proxy cores, the policy engine, the secret store, eval libraries and
tracing. Build the registry, the interpreter, the scope and approval layer, cases, queues and SLAs,
and the release gate. The table gives the choice per component, with what phase 1 needs.

| Component | Same for every bank? | Adopt (candidates) | Build thin | Phase 1 (first email workflow) | Later |
|---|---|---|---|---|---|
| Execution engine | Yes | Temporal | Interpreter workflow, plan compiler | Yes (ADR-0001) | |
| Agent Builder registry and release gate | No: risk tiers, owners, edit classes, gate steps are the bank's | none fits | Registry, versioning, pointers, templates, gate composition, publish four-eyes | Registry, versions, email template, gate with four-eyes publish | Gate steps per risk tier configurable in the console |
| Canvas | Partly | React Flow (already in the mock) | Node palette, inspector, checks | Read-only graph view of the template | Editable canvas (problem statement: canvas sequenced second) |
| Data gateway: proxy core | Yes | Envoy-based gateway (Envoy AI Gateway reached 1.0 on 2026-06-23 with an MCP gateway, then joined the Agentic AI Foundation as "Agent Router" on 2026-09-10, [summary][envoy-aig], secondary), Kong Gateway (Apache 2.0 core), or the bank's API gateway | Module registry, scope and approval model, OPA policies, call log, MCP and OpenAPI adapters | Module registry, scopes with expiry, call log, MCP adapter, the modules the first workflow needs | Module self-publishing by system teams, revoke UI |
| Data gateway: connectors | Yes | MCP servers, OpenAPI clients, bank-run n8n via MCP, vendor SDKs | Module manifests, owner workflow | Two or three modules (CRM lookup, document store, reply-by-mail) | Catalogue growth driven by workflow demand |
| AI gateway | Mostly | See ADR-0008 | See ADR-0008 | Yes, minimal scope (ADR-0008) | ADR-0008 |
| Evals harness | Partly | Promptfoo (open source, acquired by OpenAI March 2026, stated to remain open source, [Promptfoo][promptfoo]), Inspect AI, DeepEval (not assessed, **unverified**) | Suite storage, baselines, scoring rules, gate integration, evidence bundles, "re-run every workflow citing a changed policy" | Sample-mail suite per workflow, baseline compare, evidence bundle on publish | Vendor-model-update runs, policy-change re-runs, reviewer overrides into the set |
| Tracing and LLM observability | Yes | OpenTelemetry; Langfuse (MIT core, acquired by ClickHouse 2026-01-16, [ClickHouse][langfuse]) | Correlation of run, case and gateway ids | OpenTelemetry ids across run, case and gateways | Langfuse or equivalent if the bank wants prompt-level analysis |
| Policy engine | Yes | OPA | Policies | Yes | |
| Secrets | Yes | Bank's store; OpenBao or Vault | none | Yes | |
| Cases, queues, SLAs | Generic in principle | ServiceNow, Salesforce Service Cloud, Pega (if the bank already runs one) | Thin case model in PostgreSQL owned by the platform, with optional sync to the bank's case system as a tool module | Yes: cases, queues, SLA timers, per-action approval | Sync to an external case system if [open question 9](../overview.md#open-questions) requires it |
| Mailbox intake | Mostly | Microsoft Graph delta query, polled every 60 s per folder; the bank's existing mail security scanning | Intake adapter: delta tokens per folder, de-duplication by message id, archive to WORM, hand-off to a run | Yes, polling only | Graph change notifications through an inbound endpoint or Azure Event Hubs after the bank's network review; further intake types (portal uploads, scanned post) on the same pattern |
| Identity | Yes | Bank IdP, SPIFFE/SPIRE or platform equivalent | Workflow and platform identity registration, approval-token signer | Yes (ADR-0005 phase line) | User delegation |
| Chat surface | Partly | See ADR-0009 | See ADR-0009 | No | ADR-0009 |

### Mailbox intake polls in phase 1

Phase 1 mailbox intake polls Microsoft Graph delta queries every 60 s per folder, and no inbound
endpoint is opened. Phase 1 polls rather than subscribing because a change notification needs either an HTTPS endpoint
that Microsoft Graph can reach from the internet or an Azure Event Hubs subscription, and both need a
network review the first workflow should not wait for. Polling every 60 s is well inside SLA clocks
measured in hours (`03` 5.6.3). Either way, Graph access to shared mailboxes uses application
permissions; the `.Shared` delegated scopes do not support notifications ([Graph][graph-notif]).
Granting an application access to specific mailboxes only is an Exchange administration task, which
is the one step in adding a mailbox that depends on another team (see
[Throughput](../overview.md#throughput-the-marginal-cost-of-workflow-n)). The same constraint applies
to SharePoint change notifications for knowledge sources, so phase 1 SharePoint sources also poll
delta (`02` 5.5).

### Why cases are built thin

The problem statement's reference flow makes cases, queues and SLA timers platform primitives, and
the [end-to-end sequence](../overview.md#end-to-end-the-email-to-workflow-reference-flow) shows why: the SLA timer, the wait for approval and the approval token all have
to be in the same transactional boundary as the run. If the case lived only in an external product,
every decision would cross an integration that can fail between "approved" and "executed". The case
model stays small (case, queue, assignee, SLA, drafted actions, decisions) and syncs outward when the
bank requires its case system to remain the record ([open question 9](../overview.md#open-questions)).

## Consequences

The platform team owns and operates more components than a single-product purchase would give it:
the registry, interpreter, scope layer, cases and gate. Each adopted component is replaceable behind
the interface the platform defines for it, so a product change (for example a different AI gateway
data plane) is a configuration change and a re-test rather than a rewrite.

## Phase 1 vs later

The per-component phase split is in the table's "Phase 1" and "Later" columns.

## Sources

[envoy-aig]: https://www.truefoundry.com/blog/envoy-ai-gateway-review
[graph-notif]: https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview
[langfuse]: https://clickhouse.com/blog/clickhouse-acquires-langfuse-open-source-llm-observability
[promptfoo]: https://www.promptfoo.dev/blog/promptfoo-joining-openai/
