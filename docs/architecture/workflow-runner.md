# Workflow runner

Status: agreed design, 2026-10-16; slice 1 is card an earlier change. The runner is built on LangGraph, made resilient with a step
journal, a Postgres queue and worker processes. Node types and instances, the catalogue, and the runner options
weighed with their sources: [workflow nodes](../design/workflows/workflow-nodes.md). This page replaces the 2026-10-15 proposal.

## 1 What the runner is, and what it is not

The runner executes published workflow definitions: node instances of registered types joined by ports. It is a
predictable machine. Intelligence enters only through nodes: an agent node runs a kernel turn, an AI node runs one model
call against a schema, and the runner records what each returned.

It is not the chat system. A conversation with an agent runs on the agent's own graph and never on the runner. An agent
can call a workflow as a tool, and a workflow can contain an agent node; both cross the boundary in section 2.

## 2 The split from agents

| Package or service | Owns | Imports |
|---|---|---|
| `packages/ops_engine` | Type registry, v2 compiler to LangGraph, node wrapper, journal, queue claim, worker loop | LangGraph, `ops_store`, `ops_service_kit`, `ops_agent_kernel` (its `KnowledgePort`), `ops_checkpointer` (its fence error); never `ops_agents` |
| `services/agents-service` | Agents, chat, the kernel, the adapters below, the worker process host | `ops_engine` |
| tools-service | Tool registry and the gateway every tool call passes | none of the above |

The engine reaches everything outside it through ports, so it can move to its own service by moving the package:

| Port | Called by | Provided today by |
|---|---|---|
| `AgentPort.turn(request) -> result` | Agent node | the kernel in agents-service; `request.output_schema`, `result.output` |
| `ToolPort.call(operation, input, key, generation, token)`, `.find(key)`, `.mint(run, call, approval)` | Call a tool, Send message; reconciling a write by key; the token for a reviewed write, minted at the call | tools-service `POST /v1/calls` and `GET /v1/executions?key=`; recorded review approvals |
| `ReviewPort.open(...)`, decision arrives as a resume | Human review | the Reviews facade |
| `FilesPort.parse(file_ids)` | Parse | the files library |
| `KnowledgePort.search(query, kb_ids, k)` | Answer from knowledge | the kernel's existing knowledge port (`ops_agent_kernel/ports.py`), backed by kb-service |
| `TimerPort.set / cancel` | Human review SLA, Wait | the timers table |
| `RunPort.start(workflow, inputs, mode)` | Start workflow | the engine itself, through the queue |
| `LeasePort.acquire / heartbeat / release` | The worker, per claimed run | the thread lease and its generation (`thread_leases`) |
| `EventPort.append(run, team, type, node, data, generation)` | The worker | `thread_events`, fenced by the lease generation |
| `StepHooks.after_step(run, node, status)` | The node wrapper, once a step's row is finished | nothing in production; the dev-only crash fault of uc-081 |

`check_standards` lists `ops_engine` in its layer order after `ops_checkpointer` and before `ops_agents`, and refuses an import of `ops_agents` from `ops_engine`, so the split is enforced, not described.

## 3 How a definition runs

| Definition element | LangGraph form |
|---|---|
| State | One channel per node instance holding a small envelope `{port, stepId, iteration, out}`; outputs over 8 KB are meant to live in the journal with a reference in the envelope (not built yet: outputs are held whole) |
| Out ports | Conditional edges reading the envelope's port; an unconnected out port fails publish |
| Fork and Join | A port connected to several steps runs them together; `ops.flow.join` is a LangGraph deferred node, so it runs once, after every branch that can still arrive, with each branch's output by step id (null for one an If or Switch sent elsewhere). A step two branches meet at without a Join runs once per branch, and validate warns |
| Loop | Planned: `Send` per item into a body subgraph, then a join |
| Start workflow | Starts a child run per item, keyed by run, step, iteration and item, so a retry starts none twice. Without wait it goes on by `started` once they commit. With wait it pauses on an interrupt; each child's end queues a resume naming that pause (`RunStore.settle_parents`), the step reads the children's states in one query, starts the next batch, and goes on by `done` with every outcome and output in item order (outputs read once, then), or by `timeout` after `timeoutHours` |
| Wait | Pauses on an interrupt for `seconds`, or until a date read from a step (a past date goes on at once, one that is not a date leaves by `error`); the worker queues one delayed wake keyed by run, step and iteration, so no worker is held |
| Human review | Opens the review (upsert on run, node, iteration), then one `interrupt`; the chosen option is the port. A deadline (`slaHours`, `onTimeout: expire`) and reminders (`remindEveryHours`) are delayed work on the same pause ([human in the loop](human-in-the-loop.md)) |
| Agent | Calls `AgentPort.turn` with ids derived from run, node and iteration, so tool keys repeat on a re-run; output checked against the node's schema |

### Personal data in a run

A run's data stays real, so a later step (a Send) gets the real address an earlier step found. Masking is where people
read: the run page (`GET /v1/workflows/runs/{id}`) and its event stream mask every input, output, error and decision
value when the team's `aiStepsMaskPersonalData` is on, the default (`routers/engine.py` `_values_masked`). An
Agent step and an AI step store real values whatever the agent's `redactPii` says; `redactPii` masks the agent's chats.
Review and task views show real values, because reviewers verify them.

### AI steps

Classify, Summarise, Extract from text and Draft run one model call each (`ops_engine.ai_steps.run`), and run only for a
team with `aiSteps` on, checked when the workflow is saved and again at each step. The same answer is available outside
a workflow at `POST /v1/ai-steps/{step}` (`workflows.run` in the team; the text is bounded by
`ai_step_max_text_chars`). Both read a named document type's fields through `ai_steps.resolve_fields`, as the run's team
or the caller's.

### A run's status

A parent run waits on the runs its steps started, and an End's `result` setting can mark a run failed. The full rules are in the table under "A run's status" in [agents-service overview](../services/agents-service/overview.md).

## 4 Resilience

Every node runs inside one wrapper. A node whose step row is recorded or pinned returns that output and runs nothing.
A dangling write is reconciled by its key, never attempted twice.

| Effects class | Attempts | On crash mid-node |
|---|---|---|
| none | 3 | Runs again; deterministic |
| read | 3, backoff 1 to 30 s | New attempt row |
| model | 2 | New attempt; the model ledger replays recorded responses |
| write | 1, then a reconciliation read | Found by key means done; absent means the error port |
| human | not retried | The upsert finds the same review |

Runs keep `durability="sync"` because the fence must refuse a stale owner before its next step. Leases and fencing are
unchanged. Checkpoints are deleted when a run ends; the journal is the record the console reads. A run whose resume
fails three times goes to failed with the error and a manual step.

A failed run's `error` is a sentence for people that names the step (`plain_failure`, `ops_engine/compiler.py`); the
exception's text is kept on the failed step's row and in the run's `failed` event as `detail`. A review that cannot
open, because the write it approves reads nothing from the run, is a failed step like any other. Test:
`services/agents-service/tests/engine/test_step_failure_message.py`.

## 5 Scale

| Concern | Design |
|---|---|
| Runs leave the request | `POST /v1/runs` writes the run and a start row in one transaction and returns 202 |
| Queue | `engine_work`: start, resume (review decision, timer, child end, sweeper), retry, cancel; claimed with `FOR UPDATE SKIP LOCKED`, then the thread lease |
| Workers | N processes, each running several runs; sweeper and timer poller live here |
| Tenancy | Each claimed run gets a tenant-scoped saver; per-tenant running cap; 429 with retry-after past the queued limit |
| Stream | Workers append to `thread_events`; the console re-attaches with `after=seq` |

## 6 What the console shows

| Feature | Source |
|---|---|
| Run list and run detail | `engine_runs` and `engine_steps`: each node's input, output, port, attempts, errors, duration |
| Run detail `children` | The runs this run's steps started, from each step's `runs` output, each with its status and outcome now (`started_runs`, `api/routers/engine.py:976`) |
| Run detail `files` | Every file id found at any depth in the run's input, once each in order, with the name the upload gave (`files_in`, `api/routers/engine.py:954`) |
| Test run with pinned data | Pins written as step rows before the run, honoured only in test mode |
| Retry a step, run from a node | A retry row; a new run with earlier steps copied as pins |
| Replay check | Walks the definition with recorded outputs; must reproduce the recorded path |
| Migrate a paused run | Allowed when the waiting node exists in the target version |

## 7 Versioning

Each run pins its definition version and digest; each node instance pins its type version; each work row carries the
engine build, and a worker claims only its own build's rows. An archived workflow (`archived_at` on every version,
an earlier change) starts no run of any mode and leaves the lists; runs already started finish on their pinned version. Definitions with `schemaVersion: 1` keep compiling on the
v1 compiler until no open thread pins one.

## 8 Proof

| Use case | Proves | Fails when |
|---|---|---|
| uc-081 | Basic nodes run through the queue; a worker killed after the tool step leaves the tool called once | the recorded-output lookup is removed |
| uc-082 | Court order intake in the new types: loop, agent nodes, cases started in continue mode, spam and unknown senders handled | an exit node is unreachable |
| uc-083 | Pins, retry, run from a node, replay check; 200 concurrent runs on two workers | the replay check accepts an edited output |
| uc-084 | An agent node inside a workflow; an agent finds a workflow with tool search and runs it | the workflow is not in the tool directory |
