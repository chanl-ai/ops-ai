# ADR-0003 Workflow definition format and portability

Status: accepted (draft for review). Formerly DR-3.

## Context

The product owner asked for an assessment of AWP and of whether workflows and agents can be
deployed on other platforms. Portability has three meanings that are often mixed:

| Meaning | Example | Realistic? |
|---|---|---|
| Definition portability | Export an agent block or a workflow so another tool can read and run it | Partly: agents and tools yes, through standards; whole workflows with human steps, SLAs and gates no standard covers |
| Runtime portability | Move running workflows to a different engine | Only by re-implementing our interpreter on that engine; histories and in-flight runs do not move |
| Interoperability | Other platforms call our workflows, and ours call theirs | Yes, through A2A and MCP |

### What AWP is

AWP here means **Agent Workflow Protocol**. Two things carry exactly that name, and
several unrelated projects share the acronym.

| Candidate | Publisher | What it defines | Maturity | Licence |
|---|---|---|---|---|
| Agent Workflow Protocol ([repo][awp-repo], [spec][awp-spec]) | One individual GitHub maintainer (`veegee82`) | YAML manifests (`workflow.awp.yaml`, `agent.awp.yaml`) over a seven-layer model; DAG orchestration, autonomy levels A0–A4, 32 validation rules, budgets; Python reference implementation (`awp-agents`) | Spec 1.0.0 "Draft Standard" dated 2026-03-23; repo at v0.3.2 with 19 stars and 3 forks when read; no standards body; the spec as we read it does not cover durable execution or human approval steps | Apache 2.0 (relicensed from MIT by the sole copyright holder) |
| The Agent Workflow Protocol (AWP) Well-Known Resource ([IETF draft][awp-ietf]) | Two individuals (Ajna.inc, Verid.id), individual Internet-Draft | `/.well-known/awp.json` describing a **website's** workflows (login, search, checkout) so browsing agents can act without scraping | `-00`, 2025-11-01, expired 2026-05-05, not adopted by any IETF working group | IETF Trust |
| Same acronym, unrelated ([search][awp-search]) | Various | Agent Workspace Protocol, Agent Workstate Protocol, Agentstration Worker Protocol, a token-staking "Agent Work Protocol" | Single-repo projects | Various |

**Plain finding.** As of 2026-10-04 we found no Agent Workflow Protocol with a standards body,
foundation, multi-vendor steering or more than one independent runtime. The GitHub project is the
closest match to "deploy our workflows on other platforms" and is a single-maintainer draft with a
small following. The IETF draft solves a different problem (agents using websites) and has expired.
Confidence that no widely adopted AWP exists: high. Confidence that the GitHub project is the one
intended: medium ([open question 12](../overview.md#open-questions)).

### Adjacent standards

| Standard | Governance and status | Covers | Use here |
|---|---|---|---|
| MCP | Agentic AI Foundation (Linux Foundation); current spec 2026-07-28 ([versioning][mcp-ver]) | Tools, resources, prompts between a client and a server | **Adopt** both ways: consume MCP servers as tool modules; expose approved tool modules as MCP servers to other runtimes |
| A2A | v1.0 released 2026-04-09 under Linux Foundation governance; IBM's ACP merged into it 2025-08-29; joined the Agentic AI Foundation in August 2026 ([summary][a2a-status], secondary) | Agent-to-agent task exchange, agent cards | **Adopt** for interoperability: a published workflow can be exposed as an A2A agent; a workflow node can call a remote A2A agent through the data gateway |
| Open Agent Specification (Oracle) | Oracle-led open project; latest release 26.3.1; adapters for LangGraph, AutoGen, OpenAI Agents SDK, Microsoft Agent Framework, WayFlow ([releases][agentspec-rel], [paper][agentspec-paper]) | Declarative definition of an agent and simple flows | **Export** agent blocks to it; **import** to bootstrap agent blocks. Licence of the repo not confirmed (**unverified**) |
| Open Workflow Specification (formerly CNCF Serverless Workflow) | CNCF; spec 1.0.3; runtimes include SonataFlow, Synapse, Quarkus Flow ([site][owf]) | General workflow DSL: states, events, retries, timeouts | **Watch.** Closest standard to our graph, but has no notion of agent blocks, module scopes, risk tiers or four-eyes approval. An export is feasible later |
| BPMN 2.0.2 | OMG, January 2014 ([OMG][bpmn]) | Business process diagrams with user tasks, timers, events | **Export only**, as a read-only view for Risk and Audit reviewers |
| OpenAPI 3.x and Arazzo 1.1.0 | OpenAPI Initiative; Arazzo 1.1.0 published 2026-05-17 ([Arazzo][arazzo]) | HTTP APIs; sequences of API calls | **Adopt** OpenAPI for HTTP tool modules; Arazzo import is low priority |
| AGNTCY | Linux Foundation since 2025-07-29; identity, discovery and observability layer above A2A ([summary][a2a-status], secondary) | Agent directory and identity | **Watch**; relevant to ADR-0005 if the bank federates agents across vendors |
| Microsoft Agent Control Specification | Announced June 2026 per a secondary source; primary source not read ([article][ms-acs]) | Portable governance policy for agents | **Watch**, **unverified** |
| LangGraph graphs | Library format with no standards body | Agent graphs | Imported by running them inside an agent block (Temporal plugin) |
| AWP | See above | Multi-agent YAML workflows | **Track**; revisit if adopted by a foundation or implemented by two independent runtimes |

## Options

| Option | Expresses our primitives (agent version pins, module scope, human step with SLA and four-eyes, case, risk tier, edit class) | Round-trips to the canvas | Marginal effort per new workflow | Stable governance | Portability value | Score (1–5) |
|---|---|---|---|---|---|---|
| Own versioned JSON graph with JSON Schema, plus templates | Yes, by design | Yes (the mock's `WorkflowGraph` is already nodes and edges) | Lowest: a template plus settings; forms for ops teams, canvas for builders | We own it | Through exporters | **5** |
| Open Workflow Specification as canonical | Partly; needs extensions for most primitives | Needs mapping | Medium: authors work in a general DSL | CNCF | Medium | 3 |
| BPMN 2.0 as canonical | Human tasks and timers yes; agent and scope via extensions | Needs a BPMN modeller | Medium: each workflow is a modelled diagram | OMG, stable | Medium for documentation | 3 |
| Open Agent Specification as canonical | Agents yes; human steps, SLAs, cases no | Partly | High for anything beyond an agent | Single vendor-led | Medium for agents | 2 |
| AWP as canonical | Agents and DAGs; no human steps or durability in the spec as read | Partly | High | Single maintainer | Low today | 1 |
| Code-first (Python or TS functions) | Yes | No; the canvas cannot edit code safely | Highest: every workflow is a code change and a developer ticket | We own it | Low | 1 |

**Templates.** A template is a definition with named settings and locked structure. The
email-intake template from the problem statement's reference flow fixes the shape (mailbox trigger → classify and extract →
route to case, queue and SLA → draft actions → per-action approval → execute) and exposes the
settings ops teams own: mailbox, intents with example emails, extraction fields, routing rules,
queues, SLAs, approval rules, agents and knowledge bases from the library. A workflow created from
a template stores a reference to the template version and its settings; the compiler expands it to
a full definition. Settings map to the problem statement's edit classes, so changing an SLA label is free, a
prompt fragment re-runs the suite, and an approval threshold goes back through the gate.

## Decision

The canonical format is our own **workflow definition**: a declarative JSON graph, validated by a
published JSON Schema, with a `schemaVersion`, immutable once published, addressed by
`(workflowId, version, sha256 digest)`. Every reference inside it is pinned: agent blocks by
`(agentId, version)`, tool and knowledge modules by `(moduleName, version, scope)`, gate policies by
id and version. The compiler turns it into an execution plan for the interpreter.

| Direction | Standard | What crosses | Phase |
|---|---|---|---|
| Import | MCP, OpenAPI | Tool modules | 1 |
| Import | LangGraph, existing Python agents | Agent blocks (run inside the agent-block host) | 1 |
| Export | MCP | Approved tool modules, for other agent runtimes in the bank | 1 |
| Export | A2A | A published workflow as an agent endpoint for other runtimes inside the bank (alongside the API, email and intranet chat deployments) | 2 |
| Export / import | Open Agent Specification | Agent block definitions | 2 |
| Export | BPMN 2.0 (view only) | Any version, for reviewers | 2 |
| Watch | Open Workflow Specification, AWP, Agent Control Specification | Whole workflows, policy | Revisit each half year |

"Deploy on another platform" therefore means: agent blocks and tool modules travel through MCP and
Agent Spec; whole workflows are reachable from other platforms through A2A and the API; and the
engine can be replaced by re-implementing the interpreter, which is small because the definition
holds the logic. Run histories, evidence and in-flight runs do not move between engines, and no
current standard would let them.

Every deployment and export serves bank staff or bank systems only. A public, customer-facing
deployment of a workflow is out of scope (see [ADR-0009](ADR-0009-chat-experience.md)).

## Consequences

### Strongest counter-argument and our answer

**"A bespoke format is lock-in to us. Adopt a standard so the bank is not dependent on this team."**
The format is open to the bank: a published JSON Schema in the bank's repository, with exporters.
No available standard expresses module scope with approval expiry, per-action human approval with
four-eyes and SLA, inherited risk tier, or edit classes, and those are the controls the problem statement depends
on. Adopting a standard and extending it for all of these would give a format that is standard in
name and still needs our tooling to run.

### What would change this decision

- A foundation-governed workflow standard (Open Workflow Specification, an AAIF project, or AWP
  under a foundation) adds human-task, SLA and authorisation-scope semantics and gains two
  independent production runtimes. Then we make it canonical and keep our schema as a profile.
- The bank mandates BPMN as the system-of-record format (pairs with ADR-0001's Camunda trigger).

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Definition schema v1 covering the email template's node types; compiler; email-intake template; MCP and OpenAPI import of tool modules; existing Python agents as agent blocks | A2A export, Agent Spec import and export, BPMN view, further templates (chat agent, scheduled review, document intake) |

## Sources

[a2a-status]: https://architecturediagram.ai/blog/ai-agent-interoperability-protocols
[agentspec-paper]: https://arxiv.org/pdf/2510.04173
[agentspec-rel]: https://github.com/oracle/agent-spec/releases
[arazzo]: https://spec.openapis.org/arazzo/latest.html
[awp-ietf]: https://datatracker.ietf.org/doc/html/draft-vinaysingh-awp-wellknown-00
[awp-repo]: https://github.com/veegee82/agent-workflow-protocol
[awp-search]: https://github.com/marcoloco23/awp
[awp-spec]: https://github.com/veegee82/agent-workflow-protocol/blob/main/spec/versions/1.0/spec.md
[bpmn]: https://www.omg.org/spec/BPMN/
[mcp-ver]: https://modelcontextprotocol.io/specification/versioning
[ms-acs]: https://enterprisedna.co/resources/news/microsoft-acs-agent-control-specification-enterprise-2026/
[owf]: https://open-workflow-specification.org/
