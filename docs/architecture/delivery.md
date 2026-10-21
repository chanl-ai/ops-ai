# Delivery

Status: current, updated 2026-10-16. The decided design is [workflows and agents](../design/workflows/workflows-and-agents.md); decision records it does not settle remain options.

## What is proven

The claims, their evidence and their status are in the "What is proven" table of [README.md](README.md). In short:
one API runs a chat agent and two workflows; a pause survives a restart, a crash, a graph change and a stale owner;
writes go through a policy gateway with tokens bound to their input; SLA timers fire once; storage stays bounded; the
runtime adds under 150 ms to a chat turn; the engine conformance suite passes on LangGraph; a spent budget pauses a
thread for a person; the dependency lock has no LGPL or GPL package. A person signs in through platform-service and every
service knows who is calling; tool calls and model calls leave through their gateways. Every use case passes on the
scripted model.

| Slice | State |
|---|---|
| Chat in the console on the kernel | Live locally: streaming, citations, read tools, write tools paused for approval with step-up, thread persistence, sign-in on the mock provider |
| Three graphs through the thread calls | Proven: uc-003 (simple), uc-004 (complex with fan-out, grade loop, pause, send once), uc-005 (pause survives restart) |
| Cases and Reviews in the console on runtime threads | Proven: uc-008, a paused workflow decided from Reviews resumes once and the reply is sent once |
| Durability for days-long pauses | Proven: leases, sweeper, fencing, timers, version pin, checkpoint pruning |
| Mailbox | Proven on a fake source; real tenant next |
| Approval trust | Proven: step-up verified, workflow-review requester refused, distinct money approvers (uc-009) |
| Cost and budgets | Proven on the scripted model: usage per graph model call, thread and deployment budgets, 429 on a key over budget |
| Route to people, model-call replay | Proven by the conformance suite on definition workflows |
| Identity | Proven: uc-021, uc-023, uc-025, uc-026 (sign in, refresh, sign out; members and roles; every write audited; anonymous and foreign tokens refused; another service verifies tokens from JWKS). agents-service and tools-service resolve callers through `ops_identity` |
| Tool registry and gateway | Proven: uc-010, uc-011; a module goes draft, review, published; every call runs through the registry and is logged with its verified caller |
| Import, secrets, egress policy | Proven: uc-012, uc-013; import from OpenAPI and MCP with drift; a secret never comes back; a host off the allow-list is refused at connect time |
| Agents and workflows from the console | Proven: uc-018, uc-019 (api and ui); draft, validate, test, publish with a second person; the requester is refused and a reject needs a reason |
| Chat with a workflow | Proven: uc-020 (api and ui); the reply names the waiting child and a reviewer approves its step |
| Completions through models-service | Proven: uc-028; an agent runs on the alias its publisher chose, refusals carry codes, replay by task |
| An approval outlives its token | Proven: uc-027 |

## How a claim becomes proven

| Rule | Detail |
|---|---|
| One use case per user-facing operation | `docs/usecases/<service>/<topic>.md` plus one script per layer, run by `make usecase-test` |
| Name the non-vacuous check | Each use case and experiment names the check that fails when the behaviour breaks; it is watched to fail once with its guard removed |
| Scripted model for volume | Real model calls only for an approved baseline, ten per experiment at most |
| Experiments write facts | One file per experiment under `docs/services/agents-service/experiments/`: what was built, measurements, failure modes, gotchas, verdict |
| Code from an experiment stays only if `make verify` is green and a test was watched to fail | Otherwise it is removed |

## What is next

Ordered by how much the answer could change the design.

| # | Work | Why | Cheapest proof |
|---|---|---|---|
| 1 | Mailbox on a real tenant | The first workflow's channel; large attachments and sender authentication are untested | Replay sample mail through `GraphMailSource` against a test tenant, with PostgreSQL numbers |
| 2 | Delegation token with an `act` claim from the IdP | platform-service issues the tokens today; a run acting for a person on an external IdP's authority is untested (overview open question 6) | One token exchange against a test tenant |
| 3 | The `ops_engine` runner | Slice 1 (c-061) exists; workflows still run on the agents-service graphs | Run the conformance suite through `ops_engine` ([workflow-runner.md](workflow-runner.md)) |
| 4 | Decide as the only resume door, in `ops_hitl` | Decide-then-resume exists (uc-008), but a caller of `runs` can still resume a policy-owned pause | `runs` answers 409 for a policy-owned interrupt; move the facade routes into the `ops_hitl` package under `/v1/reviews` |
| 5 | Console chat on the thread calls | Chat runs on its own routes with a dev approval token, so the gateway refuses chat writes when on | Run chat as `agent_wrapper` threads; uc-001 and uc-002 unchanged |
| 6 | Key budgets and chat metering | Thread budgets exist; key budgets admit every key and chat routes are not metered | A per-key ledger in models-service on `ops_metering`; meter chat or move it onto the graph path |
| 7 | Grading quality | The grade node is a judge prompt with unknown calibration | 30 drafts scored by the judge and by a person; agreement rate |
| 8 | A reviewer's day | The Reviews queue for days-long pauses has never been walked by a person | One operator, five paused cases |
| 9 | The first three workflows against the node catalogue | Real cases decide what the catalogue lacks | Draw them in the console and list the missing node kinds |
| 10 | Team isolation in the console | Two teams on one tenant must not see each other's agents, workflows, cases or reviews | uc-022 and uc-024 run against a second team |
| 11 | models-service on the shared auth dependency | It still trusts a static service token; agents' alias client sends that token | One call with a foreign service token refused |

## Gaps known from the experiments

| Gap | Where it is described |
|---|---|
| A gateway that dies mid-write leaves an unknown outcome; needs a reconciler | [durability-failure-and-audit.md](durability-failure-and-audit.md) |
| A recovery after the approval token's TTL has no re-review path | [human-in-the-loop.md](human-in-the-loop.md) |
| Events are stored only when a run ends; no re-attach or per-thread `seq` | [api.md](api.md) |
| Inbox race between the state check and the insert | [channels-and-deployments.md](channels-and-deployments.md) |
| Migrate checks node names only | [definitions-and-versions.md](definitions-and-versions.md) |
| Prototype trust shortcuts | [identity-and-tenancy.md](identity-and-tenancy.md#prototype-shortcuts-still-in-the-code) |
| No retention job; checkpoint pruning is not scheduled | [data.md](data.md) |

## Open decisions

| Decision | Options | Default until decided |
|---|---|---|
| May a chat user approve their own drafted write? (overview open question 18) | Never; for non-money write classes a published policy names; per risk tier | `OPS_ALLOW_SELF_APPROVAL_IN_CHAT` is true, so a chat user may approve their own drafted write; workflow reviews refuse the requester, and a money call through the gateway needs two distinct approvers |
| Graph runtime: the open-source LangGraph library or LangGraph's hosted Agent Server | Library with our leases, sweeper, timers and event log; Agent Server as a paid product | The open-source library with our own durability code; Agent Server stays an option for later |
| A generated SDK for TypeScript and Python over the one API | Build it now, so the console and CLI speak through it; or later | Not started; the console calls the API directly |
| Deploy an agent's wrapper from the console | Now, pointing the console's Deploy flow at `/v1/deployments`; or after the first workflow ships | Not started |

The engine was settled on 2026-10-16: `ops_engine` with LangGraph as the runner on PostgreSQL, with no Temporal
adapter. The decision records list further questions with defaults: the timer poll interval, the fence store in the
gateway and external schedulers ([ADR-0016](decisions/fencing-and-timers.md)).
