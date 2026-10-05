# Problem statement

Status: draft for review.

Banks want AI agents to take over routine back-office work: reading a servicing inbox, looking up
the customer, drafting the reply or the record change, and handing it to a person to approve. The
first such workflow usually takes several quarters to reach production, and the second takes almost
as long as the first. This document states why, what the platform has to provide so that later
workflows get cheaper, which decisions sit outside the platform team, and the reference flow the
first workflows follow. The specs in `docs/specs/` trace their scope to the numbered items here.

## Reasons a workflow takes quarters

Each reason has an ID that the specs cite. "Removed by" says whether the platform alone can remove
the delay or whether a decision by another function is needed (see [Decisions](#decisions-outside-the-platform-team)).

| ID | Where the time goes | Effect on the second workflow once the platform exists | Removed by |
|---|---|---|---|
| Reason 1 | Each agent is written from scratch: prompts, tool wrappers, memory, retries and connectors | Shorter: the workflow is assembled from existing modules and agent blocks | Platform |
| Reason 2 | Each system the agent touches needs its own access request, credentials and network rule | Removed: the system is already connected as a module, and the workflow requests a scoped approval on it | Decision 1 |
| Reason 3 | Security reviews the whole codebase as one block | Shorter: modules are reviewed once and reused | Decision 1 |
| Reason 4 | Risk review happens as a live demonstration in a meeting, with nothing kept | Shorter: test evidence is attached to the version under review | Decision 2 |
| Reason 5 | Testing is a person typing questions, and the results are not kept | Removed: a stored suite runs in the release gate on every change | Platform |
| Reason 6 | Each agent gets its own servers, secrets, keys and logging | Removed: all workflows share one runtime, one set of gateways and one log | Platform |
| Reason 7 | A finished workflow waits for the next release window | Removed: promotion moves a version pointer | Decision 3 |

## Decisions outside the platform team

The platform can make reasons 2, 3, 4 and 7 shorter only if three functions agree to change how
they approve work. One further rule is a mandate rather than an agreement.

| ID | Decision | Owner | Reasons it unblocks |
|---|---|---|---|
| Decision 1 | A module reviewed once by Security can be reused by many workflows, each under a scoped approval that expires | Information security | 2, 3 |
| Decision 2 | Test evidence attached to a version is acceptable input to model risk review | Model risk | 4 |
| Decision 3 | Below an agreed risk tier, promotion may move a version pointer outside the release window | Change management | 7 |
| Mandate | Every model call goes through the AI gateway | Technology leadership | 6, and agent discovery |

## Components

| ID | Component | What it must do |
|---|---|---|
| Component 1 | Agent Builder | A registry first and an editor second. Every workflow records its owner, version, risk tier and cost. A release is a numbered version promoted through one gate whose steps come from the risk tier, and rollback moves the pointer back. A visual canvas comes in a later phase and assembles a trigger, agent blocks, tool and knowledge modules, human decision steps and an output. An agent block can wrap existing Python agent code and run it on the platform runtime |
| Component 2 | Data gateway | One entry point for tools and knowledge. Each system is connected once as a module with a named owner, a scope per workflow and a log of every call. Credentials stay inside the gateway. The system's own team publishes the module and approves each workflow's use, with an expiry |
| Component 3 | Evals and testing | One suite built from real cases, run on every change including vendor model updates, scored against a baseline and read by the release gate. The results become evidence attached to the version |
| Component 4 | AI gateway | One entry point for every model call: bank-defined model aliases, spend tracking and redaction, budgets per agent, failover, and discovery of agents that are not registered but appear in traffic |

## Edit classes

A business owner edits a workflow often. What a save does depends on the class of the field edited.

| Class | Examples | What a save does |
|---|---|---|
| Free | Display text, notes, labels | Saved and logged |
| Re-test on save | Customer-facing wording, prompt fragments, choice of documents | The suite re-runs; the version cannot promote until it passes the gate for its tier |
| Re-approval | Human-decision thresholds, risk-bearing rules, module scope | Creates a new version that goes through the gate at the workflow's risk tier |
| Locked | Model, module scopes as policy, gate composition, risk tier | Changed only by the platform team and the risk function |

## Knowledge requirements

| ID | Requirement |
|---|---|
| Knowledge requirement 1 | Every source item carries department, owner, effective date and what it supersedes; an item missing required metadata is not ingested |
| Knowledge requirement 2 | Departmental boundaries hold, and a scope test proves it |
| Knowledge requirement 3 | Precedence between sources is written down, and each answer states which rule it followed |
| Knowledge requirement 4 | Freshness: content is re-indexed on publish, items past their review date are flagged, and the tests of every workflow that cites a changed policy re-run |
| Knowledge requirement 5 | Citations point to section, page and version, and are logged with the decision that used them |
| Knowledge requirement 6 | Tables and rules are returned as values the agent can use, rather than as prose |
| Knowledge requirement 7 | Sensitivity is a property of the source and travels with each passage; redaction happens at the gateway |
| Knowledge requirement 8 | Retrieval quality is measured per department against a golden set |
| Knowledge requirement 9 | Staff (contact centre, relationship managers) query knowledge through the same entry point as agents |
| Knowledge requirement 10 | Curation is a named role: one knowledge owner per department, with a monthly review |

## Reference flow: email to workflow

Shared mailboxes become routed cases with drafted actions. Each operations team configures its own
path on shared platform layers.

| ID | Step | What happens | What the operations team configures | Shared platform layer |
|---|---|---|---|---|
| Flow step 1 | Read | The mailbox is ingested and every attachment is read | Which shared mailbox to connect | Mailbox intake: shared mailbox sync, security scan, archive |
| Flow step 2 | Understand | The request is classified and its key details extracted | Categories and intents, defined with example emails | Classification, field extraction and attachment summaries per team |
| Flow step 3 | Route | A case opens in the right queue and the SLA clock starts | Routing rules, queues and SLAs | Cases, team queues, routing and SLA timers |
| Flow step 4 | Prepare and approve | Agents look up data and draft actions; a person approves each action | Which steps need sign-off, and by whom | Agents and the review workbench |

Under every step sit the data gateway (systems of record such as the CRM, core banking and the case
management system) and governance (audit trail, access control, model evaluation and monitoring).

**Versioning rule.** Every configuration change is versioned, tested on sample mail, then published.

Consequences for the specs: cases, queues and SLA timers are platform primitives, so no workflow
implements them in its own code. Each drafted action is approved separately.

## Adapting existing code

Banks usually have prototype agents already. The platform takes them in piece by piece.

| Existing piece | Becomes |
|---|---|
| Connector classes | Tool modules |
| Retrieval scripts | Knowledge modules |
| Agent graph code | An agent block on the platform runtime |
| Prompt files | Versioned prompt fragments |
| Retry, error and handoff code | Runtime behaviour plus a human-step block |
| Test scripts | Cases in the shared suite |
| Deploy scripts | Retired; promotion moves a pointer |

## Governance

| ID | Rule |
|---|---|
| Governance 1 | Release gate steps are set by risk tier, and a workflow inherits the highest tier among its blocks |
| Governance 2 | Human review is a block in the workflow, and reviewer overrides feed the test set |
| Governance 3 | Tool calls are constrained by module scope enforced at the gateway, never by prompt wording |
| Governance 4 | Prompt-injection cases are scored in the suite, with a threshold that blocks release |
| Governance 5 | An agent's entitlement is the intersection of the module scopes and the entitlements of the person or process it acts for |
| Governance 6 | Log retention and legal hold have a named owner before the first workflow goes live |

## Operations

| ID | Rule |
|---|---|
| Operations 1 | The gateways are at least as available as the most demanding workflow that depends on them |
| Operations 2 | When a dependency is down, the workflow degrades into the human step |
| Operations 3 | Each workflow pins its module versions; rollout is staged, and a module can roll back independently |
| Operations 4 | Every component has a named owner and an on-call rota |

## Principles

| ID | Principle |
|---|---|
| Principles 1 | No forced migration. Existing agent runtimes stay behind adapters and move through discover, observe, register, instrument and adopt |
| Principles 2 | Buy what is the same for every bank. Build thin, and only where the work depends on this bank's systems, entitlements, policies and risk tiers |
| Principles 3 | The canvas comes second, after forms and templates work |
| Principles 4 | The platform team owns the runtime, the gateways and the gate mechanics. Modules are owned by the teams that wrote them |

## Stop condition

If the second workflow is not materially faster to deliver than the first, the programme stops and
the approach is re-examined. The implementation plan (`docs/plan/implementation-plan.md`) defines
the measurement.
