# Inside the runtime

Status: current, updated 2026-10-16. The owner's decided design is `.codeloop/wiki/concepts/system-overview.md`; ADRs that it does not settle remain options.

The runtime is `agents-service` (`services/agents-service`, module `ops_agents`), one FastAPI process on port 8700.
Detail on the kernel is in [agent-kernel](../../.codeloop/wiki/concepts/agent-kernel.md), on nodes in
[interpreter-and-nodes](../../.codeloop/wiki/concepts/interpreter-and-nodes.md), on layout and the verify gate in
[python-service-skeleton](../../.codeloop/wiki/concepts/python-service-skeleton.md).

## Parts

| Part | Where | What it does |
|---|---|---|
| Runtime API | `ops_agents/api/app.py`, `routers/` | Thread, run, state, migrate, versions, approvals, step-up, route-to-people, timers, deployments, inbox, chat routes (a facade over agent_wrapper threads). Its lifespan starts the sweeper and the timer poller in the same process |
| Run executor | `ops_agents/api/runs.py` | `execute()`: one path for routes, sweeper, timers and inbox drain. Takes the lease, raises the checkpoint fence, streams the graph with `durability="sync"`, heartbeats, journals, syncs timers, releases, drains the inbox |
| Agent kernel | `packages/ops_agent_kernel` | One agent turn on Pydantic AI: context assembly, the loop, tool calls through a `ToolExecutor` port with idempotency keys, a gated write ends the turn as an `Interrupt`, resume from a decision, kernel events (status, text delta, tool input and output, citations, interrupted, finished). Holds no state between turns |
| Workflows as tools | `api/child_runs.py`, `graphs/common.py` (`WorkflowRunner`, `WorkflowTools`) | An agent granted `workflow:<id>` calls a published workflow as a tool; a child thread on it is linked by `parent_thread_id`, and its result or review handle comes back as the tool result ([workflows-as-tools.md](workflows-as-tools.md)) |
| Graphs | `ops_agents/graphs/` | Three code graphs and the definition compiler; `common.py` bridges a kernel turn into a node |
| Definition compiler | `graphs/definition.py` | Validates a definition, builds a LangGraph `StateGraph`, caches compiled graphs by digest |
| Checkpointer | `packages/ops_checkpointer` | `AsyncpgSaver`: LangGraph checkpoints on asyncpg with tenant row-level security and a per-thread fence |
| Leases and sweeper | `api/leases.py`, `api/sweeper.py` | Per-thread lease with generation; takeover of expired leases; recovery from the last checkpoint |
| Timers | `api/timers.py`, `api/timer_port.py`, `graphs/sla.py` | SLA timers, the poller, `fire()` |
| Activities | `ops_agents/activities/` | Seed catalogue, local tools, keyword knowledge store, `GatewayToolExecutor` for tools-service |
| Channels | `api/channels/` | Mailbox adapter, deployment and inbox store |
| Metering | `graphs/metering.py`, `api/metering.py`, `api/usage.py`, `packages/ops_metering` | A usage row per model call; the budget check before each call, which pauses the thread when spent |
| Model-call ledger | `api/model_ledger.py` | Records each completed model response by thread and request hash, under the alias it ran on; a node re-run after a crash replays it instead of calling the model again |
| Model source | `ops_agent_kernel/models.py`, `ports.py` (`ModelSource`), `api/model_ledger.py` (`LedgerSource`) | The model a turn runs on, by its agent's alias: through models-service when it is configured, else the one direct model ([Which model a turn runs on](#which-model-a-turn-runs-on)) |
| Route to people | `api/routing.py`, `routers/routing.py` | Stops a definition workflow at the next step end with no write in flight, journals the skipped steps, and raises the built-in `manual_handling` step |

## One turn and one run

Console chat takes the same path: a message is a run on the conversation's agent_wrapper thread under its lease, and the node streams the kernel's events (text, tool calls, citations, status, the turn's model) into the event log, from which the stream frames and the stored messages are both built.

A run is `graph.astream(input, config, stream_mode=["tasks", "custom", "updates"], durability="sync")` under the
thread's lease, with `max_concurrency` 4 and `recursion_limit` 60. An agent node calls the kernel; the kernel runs the
Pydantic AI loop with deferred tools, so a write the agent asks for ends the turn with `DeferredToolRequests`. The node
returns the request, the graph moves to an approval node that does nothing before `interrupt()`, and the run ends
`interrupted`. On resume LangGraph re-runs the approval node from its start, returns the decision, and the next node
resumes the kernel with `DeferredToolResults`.

| Rule | Why |
|---|---|
| The approval interrupt is its own node, placed before any side effect | LangGraph re-runs an interrupted node from its start, so work before `interrupt()` would run twice |
| A gating interrupt carries `call = {tool, input, step}` | The approval token must bind to exactly what will run; rebuilding the call from state could bind to something else |
| The kernel builds its agent per turn | No hidden state survives a process restart |
| State holds references to attachments and model outputs | A checkpoint stores the whole state per superstep ([durability-failure-and-audit.md](durability-failure-and-audit.md)) |

## Which model a turn runs on

An agent names a model alias when it is published; the publish request is refused when models-service does not list
it as a chat alias, and `GET /v1/model-aliases` lists the same set for the console's picker. With `OPS_MODELS_URL`
and `OPS_MODELS_KEY` set, the kernel asks `KernelPorts.models` for the turn's alias: one OpenAI-compatible model per
alias, pointed at models-service's `/v1/models/chat/completions` with agents-service's key, wrapped once in
`LedgerModel`. models-service resolves the alias, holds the provider key, meters, and enforces the key's rate limit,
budget and the alias's sensitivity clearance (ADR-0008). Without the key, every turn runs on the direct model built
from a provider key in this process, and only the runtime's alias can be published.

| Rule | Why |
|---|---|
| The OpenAI client runs with `max_retries=0` | Its default retries a 429 twice: one over-limit turn would spend the limit three times and arrive late |
| Inside a graph run each request carries `X-Thread-Id`, `X-Run-Id`, `X-Step-Id` and `X-Request-Hash` | models-service's call-log row joins the model-call record that replays it; the headers never go to a provider directly |
| Graph models (classify, extract, grade) get the unwrapped runtime alias | Their calls are metered by `MeteredModels`; wrapping them in `LedgerModel` too would count each call twice |
| A refusal keeps its HTTP status and code on the turn result | The test turn answers 429, 403 or 404 with models-service's code (other refusals 503); a chat stream's error frame and the stored message carry `errorCode` |

The hop costs 7 ms at p50 on a local server (E13, [models-service-hop.md](../services/agents-service/experiments/models-service-hop.md)).

## Graphs

| Graph | Nodes | Pause | Use |
|---|---|---|---|
| `agent_wrapper` | agent turn → approval → resumed turn | Before a gated tool | An agent deployed on a channel; and console chat: each conversation is a thread on it, each message a run |
| `simple_workflow` | classify → answer with citation | None | Reference for a workflow with no pause |
| `complex_workflow` | classify → extract per attachment (Send fan-out, at most 20) → collect → draft → grade (redraft until 0.8 or 3 attempts) → human → send reply | Human review of the draft | Reference for a days-long case |
| Definition-built | Node kinds agent, extract, collect, draft, grade, condition, human, tool, end; built-in `route_to_people` and `manual_handling` | `human` nodes, with SLA settings; `manual_handling` after a route to people | Workflows published as JSON |

Every run, resume and state read compiles the thread's pinned version and refuses if the stored digest no longer
matches. Compile takes about 3 ms; a cache hit 0.06 ms. The cache matters for memory: each pinned version stays
compiled in each process while any thread can resume on it
([pause-survives-graph-change](../services/agents-service/experiments/pause-survives-graph-change.md)).

## What LangGraph gives and what our adapter adds

| From LangGraph | Added by us |
|---|---|
| State saved after every superstep; interrupt and resume; Send fan-out with fan-in and a concurrency cap; a recursion limit; state read-back (values, next nodes, pending interrupts, history) | Our checkpointer on asyncpg with RLS ([data.md](data.md)) |
| | Leases with generation, heartbeat every TTL/3, sweeper ([durability-failure-and-audit.md](durability-failure-and-audit.md)) |
| | Fences in the checkpointer, the journal, timers and tools-service |
| | Timers table, poller and `fire()` ([human-in-the-loop.md](human-in-the-loop.md)) |
| | Version pin per thread and compile from stored JSON ([definitions-and-versions.md](definitions-and-versions.md)) |
| | Run journal, duplicate-run replay by run id, one event shape over LangGraph's three stream modes |
| | Find-or-create by external key and an inbox for input on a busy thread |
| | Usage and budgets per thread, a model-call ledger replayed on re-run, route to people |

Designed and not built: a work queue table for enqueued runs and worker pools per tier, a stored event log with
per-thread `seq`, recovery handed to its own task with a cap (today recovery runs inside the sweep loop, one thread at
a time).

## Process types

| Process | Today | Designed |
|---|---|---|
| `api` | One process serves routes and runs the sweeper and the poller | Serves routes and streams; scales with edits and chat connections |
| `worker` | None | Takes runs from the work queue; owns timers and the poller; scales with concurrent runs |
| tools-service | Separate process on 8720 | Own deployable under its own user, so egress stays separate on one machine |

## The engine

The owner removed Temporal on 2026-10-16. The engine is `packages/ops_engine`: a step journal, a Postgres work queue,
worker processes, leases with generation fencing and reconcile-by-key, with LangGraph as the runner on PostgreSQL
([workflow-runner.md](workflow-runner.md)). Slice 1 (c-061) is in code and runs inside agents-service; the agent and
chat routes still call LangGraph directly. The conformance suite, 13 tests from spec 16 §9 and ADR-0016, runs on the
LangGraph adapter (`services/agents-service/tests/conformance/`,
[conformance-suite](../services/agents-service/experiments/conformance-suite.md)). Plans must keep every side-effecting node idempotent by key
or a single attempt with a reconciliation read, carry no engine-specific settings, and wait only through `delay`,
`wait for event` or `human step`.

## Libraries

Every package, version, licence and network behaviour is in [dependencies.md](dependencies.md). The licence and
network facts that shape the architecture:

| Fact | Consequence |
|---|---|
| The checkpointer is our own on asyncpg (Apache-2.0), not LangGraph's psycopg (LGPL-3.0) saver | The lock has no LGPL or GPL package |
| certifi and orjson are MPL-2.0, which is copyleft per file | Using them unmodified carries no obligation on our code; a modified file must be published |
| tiktoken downloads its BPE encoding on first use | Vendor the encoding file into the image and set `TIKTOKEN_CACHE_DIR` to it |
| langsmith and genai-prices can call out | A deployment sets no `LANGSMITH_TRACING` or key; the runtime never calls the price update; `make run` sets `PYDANTIC_AI_NO_BANNER=1` |
| Under a socket guard the service made zero outbound attempts except tiktoken with an empty cache | Default-deny egress catches anything missed |
