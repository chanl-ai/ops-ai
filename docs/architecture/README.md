# Ops AI architecture

Status: current, updated 2026-10-16. The owner's decided design is `.codeloop/wiki/concepts/system-overview.md`; ADRs that it does not settle remain options.

Ops AI is one operational AI platform for regulated enterprises, banks first. Agents and workflows are its two ways
of running work; both use the same shared services and the data and AI gateways. Builders draw agents and workflows in
the console, publish them through a review, and deploy them on channels (console chat, a shared mailbox, an API, an
MCP endpoint, a schedule). Today every run is a graph executed on a thread by one Python service, `agents-service`,
which saves state after every node in PostgreSQL, pauses for a person for as long as a case needs, and resumes on a
reviewer's decision. Model calls and tool calls leave through gateways that hold the keys, check policy and log every
call. This folder describes the system as built and as designed, with the gotchas the experiments found.

## Reading order

| Chapter | File | What it answers | Who reads it |
|---|---|---|---|
| One page | [overview.md](overview.md) | The rule, the picture, the six services, the three run kinds, what runs today | Day one |
| Words | [words-and-entities.md](words-and-entities.md) | Graph, thread, run, interrupt, lease, fence and the other terms, and how the entities relate | Day one |
| The API | [api.md](api.md) | The call families, request conventions, the event schema, which calls exist in code | Day one |
| Services | [service-map.md](service-map.md) | Service boundaries, naming, packages versus services, deployment targets, migration steps | Day one |
| Inside the runtime | [runtime.md](runtime.md) | API process, kernel, compiled definitions, graphs, the LangGraph adapter, the engine, libraries | Builder |
| Human in the loop | [human-in-the-loop.md](human-in-the-loop.md) | Interrupts, reviews, approval tokens, step-up, two approvers, SLA timers | Builder |
| Agent guardrails and skills | [agent-guardrails.md](agent-guardrails.md) | Pinned guardrails and skills, the check before and after the answer, fail-closed exits, what is enforced | Builder |
| Tool lifecycle | [tool-lifecycle.md](tool-lifecycle.md) | Connect, import, review, access, grant, call, approve and show a tool, with what is built and what is not | Builder |
| Channels | [channels-and-deployments.md](channels-and-deployments.md) | Deployments, the adapter contract, identity per channel, external keys, the mailbox adapter | Builder |
| Identity | [identity-and-tenancy.md](identity-and-tenancy.md) | Sign-in, delegation, process principals, the tools gateway, tenancy, prototype shortcuts | Builder |
| Versions | [definitions-and-versions.md](definitions-and-versions.md) | Draft to publish, pointers, the pin per thread, migrate | Builder |
| Durability | [durability-failure-and-audit.md](durability-failure-and-audit.md) | Leases, sweeper, fencing, re-execution, idempotency, timers, side-effect classes, the journal | Builder |
| Data | [data.md](data.md) | Tables per service, the checkpointer's tables, retention, growth and pruning | Builder, operator |
| Operations | [operations.md](operations.md) | Running it, health, logs, the acceptance gate, what to watch, runbooks | Operator |
| Make | [make.md](make.md) | Make layout, ports, environment names, daily commands | Operator |
| Dependencies | [dependencies.md](dependencies.md) | Every Python package in the lock with licence and network behaviour | Operator, approver |
| Delivery | [delivery.md](delivery.md) | What is proven, what is next, the open decisions | Approver |
| Decisions | [decisions/](decisions/) | The decision records, each an option unless the owner settled it; several are superseded in part by the 2026-10-16 decisions | Approver |

## What is proven

Experiments are under `docs/services/agents-service/experiments/`; use cases under `docs/usecases/` and run with
`make usecase-test UC=<id>`. Use cases run on the scripted model; experiments marked "real model" used a small number
of real calls.

| Claim | Evidence | Status |
|---|---|---|
| A chat agent, a simple workflow and a complex workflow run through the same four thread calls | uc-003, uc-004; `services/agents-service/scripts/prove-graphs.py` (real model) | Holds |
| A chat turn streams an answer with a citation | uc-001 | Holds |
| A write tool pauses the turn, and an approval with step-up resumes it | uc-002 | Holds on the `/chat` path, which still uses a dev approval token |
| A paused workflow decided from the console's Reviews resumes once, and a repeated decision does not resume again | uc-008 | Holds |
| A paused thread survives a SIGKILL and a restart | uc-005; [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds |
| Our asyncpg checkpointer passes LangGraph's conformance suite (81 cases) and removes every LGPL package | [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds |
| Row-level security on the checkpointer tables stops one tenant reading another's checkpoints | [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds in tests; the service runs as one tenant today |
| A thread paused on version 1 finishes on version 1 after versions 2 and 3 are published | [pause-survives-graph-change](../services/agents-service/experiments/pause-survives-graph-change.md) | Holds |
| Two processes cannot run one thread; a run killed mid-node is recovered by the sweeper in about 5.5 s | [leases-and-sweeper](../services/agents-service/experiments/leases-and-sweeper.md) | Holds |
| A stale owner cannot write after a takeover: checkpoints, journal, status, timers, tool writes | [fencing](../services/agents-service/experiments/fencing.md), [fence-on-takeover](../services/agents-service/experiments/fence-on-takeover.md) | Holds, with the residuals listed in durability-failure-and-audit.md |
| A write tool runs only with an approval token bound to its input hash; money needs two approvers | [gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md); uc-007 | Holds, with the [prototype shortcuts](identity-and-tenancy.md#prototype-shortcuts-still-in-the-code) |
| Step-up is verified for signature, subject and age; a workflow review's requester cannot decide it; one person cannot be both money approvers | [approval-trust](../services/agents-service/experiments/approval-trust.md); uc-009 | Holds; `POST /v1/threads/{id}/approvals` has no requester check |
| An approved write re-sent after a crash runs once at the gateway | [gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md) | Holds |
| SLA timers warn, breach, escalate and time out into the outcome pinned in the definition | uc-006; [timers-and-sla](../services/agents-service/experiments/timers-and-sla.md) | Holds |
| Checkpoint storage stays bounded with references in state and pruning after the journal | [checkpoint-growth](../services/agents-service/experiments/checkpoint-growth.md) | Holds |
| The runtime adds under 150 ms to a chat turn | [chat-turn-latency](../services/agents-service/experiments/chat-turn-latency.md) (real model) | Holds: 52 to 89 ms at p50 |
| Redelivered mail opens no second case; replies to a busy case queue in order | [mailbox-adapter](../services/agents-service/experiments/mailbox-adapter.md) | Holds on a fake mail source; a real tenant is not run |
| The lock has no copyleft beyond file-level MPL-2.0, and makes no outbound call under a socket guard except tiktoken's first download | [dependencies.md](dependencies.md) | Holds with one condition: vendor the tiktoken encoding |
| Delegation tokens with an `act` claim from the IdP | Not run | Open |
| The engine conformance suite passes on the LangGraph adapter (13 tests) | [conformance-suite](../services/agents-service/experiments/conformance-suite.md) | Holds; no `Engine` interface and no second engine yet |
| A re-run agent node replays its recorded model call; route to people stops a workflow at a step end and skips the rest | [conformance-suite](../services/agents-service/experiments/conformance-suite.md) | Holds on the LangGraph adapter |
| Every graph model call writes a usage row; a thread pauses for a person when its budget is spent; metering adds about 3 ms per call | [cost-and-budgets](../services/agents-service/experiments/cost-and-budgets.md) | Holds on the scripted model; chat routes are not metered and key budgets admit every key |
| A person signs in, refreshes and signs out; members and roles; every write is audited; anonymous and foreign tokens are refused; another service verifies tokens from JWKS | uc-021, uc-023, uc-025, uc-026 | Holds |
| A builder manages a tool module; every call runs through the registry and is logged with its verified caller | uc-010, uc-011 | Holds |
| Tools import from OpenAPI and MCP; a credential is a secret that never comes back; egress only to allowed hosts | uc-012, uc-013 | Holds |
| An agent and a workflow go from draft to published with a second person's approval, from the API and the console | uc-018, uc-019 | Holds |
| Chat starts a workflow and a reviewer approves its step | uc-020 | Holds |
| An agent runs on the model alias its publisher chose, through models-service | uc-028 | Holds on the scripted model |
| An approval outlives its token | uc-027 | Holds |
| In-run grading agrees with a person | Not run | Open |

## Conventions in this folder

| Convention | Meaning |
|---|---|
| "In code" | The behaviour exists in `services/` or `packages/` and a test or use case exercises it |
| "Designed" | Written in a decision record, a spec or here, with no code yet |
| `path:line` | Given only where a reader has to open the code to act |
| Specs and decisions | Hold the detail; these pages hold the decision and link to them |
