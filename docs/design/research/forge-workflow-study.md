# Forge workflow system study

Status: research note. Studied `nihalashetty/Forge` at commit `25074df07b9872912902b323706a01dd47cd8477` (2026-10-06). The "Ops AI today" column is a snapshot of the Ops AI repository at the time; node forms and several node types have been built since.

Forge is an open-source workflow engine built on the same base as Ops AI's workflow runner: LangGraph compiled from a JSON definition. What does a working engine on that base do about node types, data mapping, loops, human steps, triggers and versioning, and what should Ops AI take, adapt or skip? This study reads Forge's code and answers that per concern.

Licence: Forge is MIT (`LICENSE`, copyright 2026 Nihal A Shetty), so code may be copied as well as ideas, provided the MIT notice travels with any copied file. Paths below are relative to the Forge repo root unless they are Ops AI paths, which are named as such.

## What Forge is

Forge is a self-hosted platform for building AI agents and workflows on a canvas: a FastAPI backend (`apps/api/forge`) that compiles a JSON workflow definition into a LangGraph `StateGraph`, a Next.js console (`apps/web`) with a React Flow canvas, and a shared set of JSON Schemas (`packages/schemas/forge`) that the backend validator, the compiler and the frontend config forms all read (`README.md`, "Architecture"). It runs on SQLite, embedded Chroma and an in-process scheduler locally, and on Postgres, pgvector and Redis in production. Its centre of gravity is conversational agents (chat, widget, email, MCP), with workflow nodes for routing, fan-out, loops, human input and triggers around them. The engine is the same choice Ops AI made: LangGraph v1, MIT-licensed, without `langgraph-api` (`README.md`, intro).

It is a real, working workflow engine, though a chat-first one. The backend test suite for the engine runs offline: `tests/test_engine.py`, `test_advanced_nodes.py`, `test_subworkflow.py`, `test_validation.py`, `test_tracer_interrupt.py` and `test_triggers.py` gave 43 passed in 6.6 s on Python 3.12 with no provider keys set, because a `fake:` model ref returns an offline chat model (`apps/api/forge/engine/models.py:61-93`).

## Workflow model and runner

All paths in this section are under `apps/api/forge/` unless stated.

### The definition

A workflow row stores two JSON documents: `canvas` (React Flow shape, owned by the UI) and `executable` (the compiler input, owned by the backend), plus `status` and `active_version` (`models/entities.py:65-74`). The executable is validated against `packages/schemas/forge/workflow.json`:

| Field | Meaning | Wired? |
|---|---|---|
| `id`, `version` | identity; version is an integer ≥ 1 | yes |
| `state` | map of field → `{type, reducer}`; types `list[message]`, `list[str]`, `list[json]`, `str`, `int`, `float`, `bool`, `json`; reducers `add_messages`, `add`, `last`, `merge` (`workflow.json:37-48`) | yes, compiled to a `TypedDict` with `Annotated` reducers (`engine/state.py:43-63`); `messages` is always added |
| `entry_node` | first node after START | yes (`engine/compiler.py:183`) |
| `nodes[]` | `{id, type, config, position}`; `config` validated against the node type's own schema | yes |
| `edges[]` | `{source, source_handle, target, target_handle, condition, branches}` | yes; `branches` + `condition` become a conditional edge (`compiler.py:164-174`) |
| `global_middleware` | prepended to every agent node's middleware stack | yes |
| `error_policy` | `halt`, `continue`, `route_to_error_node` (`workflow.json:22`) | partly: only `continue` is read, and only to isolate fan-out item failures (`compiler.py:114,133`); `route_to_error_node` appears nowhere in the Python code |
| `on_error` | `{message, escalate}` fallback reply on a failed run | yes, for text channels (`services/runs.py:808-812`, `tests/test_error_workflow.py`) |
| `timeout_seconds` (600), `max_concurrency` (8) | declared with defaults (`workflow.json:31-32`) | no: neither key is read by any Python file; the run wall clock comes from a global setting instead (`services/runs.py:46`) |

The schema promises three things the runner does not do. That is the first cautionary lesson: a field in the definition that nothing reads is worse than a missing field, because a builder will set it and trust it.

### Compilation

`compile_workflow(definition, ctx)` (`engine/compiler.py:76-188`) builds a LangGraph `StateGraph` in this order:

1. Build the state `TypedDict` from `state` (`compiler.py:78`).
2. Fold deep-agent sub-agents: an edge whose `source_handle == "subagents"` turns the target agent node into a callable sub-agent of the source `deep_agent` and removes it from the graph (`compiler.py:84-104`).
3. For every node, look up its `NodeSpec` in the registry and call `spec.factory(config, ctx)`, which returns a LangGraph node (a callable or a compiled sub-graph). Fan-out children are optionally wrapped for per-item error isolation and timeout (`compiler.py:122-136`, `nodes/flow.py:227-279`).
4. Wire every `end` node to `END`.
5. Routers add conditional edges from their own `cases` and `default`; their canvas edges are ignored (`compiler.py:143-150`).
6. `parallel_fanout` adds a `Send`-based conditional edge to its `child_node` (`compiler.py:152-159`).
7. Plain edges and `branches` edges are added; a failing or unmatched branch condition routes to END with a logged warning (`compiler.py:26-50,161-180`).
8. `START → entry_node`, then `builder.compile(checkpointer=ctx.checkpointer, store=ctx.store)`.

The graph is compiled per run from the stored executable (`services/runs.py:856-866`). No compiled-graph cache appears in the run paths read.

`CompileContext` (`engine/context.py:16-143`) is the dependency bundle every factory receives: tenant and project ids, checkpointer and store, tracer, materialised tools and tool sets, MCP tools, UI components, auth resolver, sandbox, egress policy, default model and provider credentials, the end user, a per-run `run_context` that never reaches the model or the checkpoint (`context.py:67-75`), agent presets and the project's other workflows (for sub-workflows). This is the same shape as Ops AI's ports: factories receive capabilities, they do not import services.

### Ordering, branching, loops, parallelism, joins

| Concern | How Forge does it | Evidence |
|---|---|---|
| Ordering | LangGraph supersteps; edges define order | `compiler.py` |
| Branching | `router` evaluates a sandboxed expression and matches `cases`, falling back to `default`, else END with a warning; `multi: true` routes to every matching case in parallel | `nodes/flow.py:44-91` |
| Edge conditions | `edges[].condition` + `branches` map | `compiler.py:26-50` |
| Loops | `loop` node increments `_loop_count` and writes `_loop = continue/done`; a router after it sends the body back; only nodes whose spec has `allows_cycle` may sit on a cycle (validator) | `flow.py:170-192`, `services/validation.py:80-114` |
| Recursion budget | derived per run: `(nodes+1)*2 + Σ max_iter*3 + 10`, floored by a setting, because LangGraph's default of 25 broke loops after about eight iterations | `services/runs.py:380-395` |
| Parallel map | `parallel_fanout` sends one `Send(child, {item_key: item, _fanout_index, _fanout_total})` per list item; results gather through an `add` reducer key | `flow.py:195-224` |
| Join | `join` is a convergence marker, or re-aggregates `input_key` with `concat`, `merge`, `first`, `last` into `output_key` | `flow.py:282-327` |
| Per-item failure | opt-in: `on_item_error: skip` or workflow `error_policy: continue` swallows one item's exception; interrupts and cancellation always propagate | `flow.py:227-279` |

### Persistence, resume and human steps

| Concern | How Forge does it | Evidence |
|---|---|---|
| Durability | LangGraph checkpointer on the top-level graph; embedded agents and sub-workflows carry none, so interrupts bubble up | `nodes/agent_node.py:1-7`, `flow.py:143` |
| Run record | `runs` row: `status` queued/running/interrupted/done/error, `input`, `output`, tokens, cost, `source` | `models/entities.py:259-276` |
| Threads | one LangGraph thread per conversation, `lg_thread_id = "{tenant}:{uuid}"`; a thread bound to one end user cannot be attached by another | `services/runs.py:426-473` |
| Human approval | `human_input` calls `interrupt({prompt, allowed_decisions, schema, timeout_seconds, timeout_default})`; resume is `Command(resume=value)`; the decision is coerced to an allowed value and written to `output_key` for a router | `nodes/data.py:80-121`, `services/runs.py:948-982` |
| Approval timeout | a reaper resumes an expired interrupt with `timeout_default`, or fails the run and notifies | `services/runs.py:1183-1300` |
| Human handoff | `handoff` interrupts; a human's reply from the agent inbox resumes the run and becomes the answer | `nodes/data.py:124-137` |
| Batched approvals | one approve/reject is replicated across several approval-gated tool calls in one turn | `services/runs.py:247-272` |
| Stale runs | a reaper marks queued runs older than 15 min and running runs older than 60 min as error | `services/runs.py:1183-1230` |
| Cancel and wall clock | cooperative cancel checked between stream frames plus a DB watcher; optional global wall-clock limit | `services/runs.py:46-120,875-899` |
| Durable streaming | the run is driven by a background task publishing to a replayable broker; SSE clients reattach with `Last-Event-ID` | `services/runs.py:136-240` |
| Queue and workers | optional arq/Redis; only webhook and schedule runs are offloaded; with no Redis, runs execute inline | `queue.py:1-57` |
| Retries | the worker retries the whole run job up to 3 times with exponential backoff, then dead-letters to a Redis list | `worker.py:25-67` |
| Node-level retries | none in the graph runner; retries live inside tools (`tools/rest.py:57-110`, idempotent methods only) and in agent middleware (`tool_retry`, `model_retry`, `model_fallback`) | `engine/middleware_compiler.py:556-582` |

The worker retry re-calls `run_to_completion`, which streams `run.input` into the graph again (`services/runs.py:878-880`). No path that resumes a failed run from its last checkpoint was found in the files read; a retry restarts the graph, so a node with a side effect can run twice.

### Triggers and scheduling

Trigger nodes (`webhook_in`, `schedule`, `email_in`, `app_event`) are passthroughs at compile time; their config drives a dispatcher (`nodes/triggers.py:1-53`). On every save, trigger nodes are mirrored into `triggers` rows (`services/triggers.py:58`, `services/workflows.py:127-141`), each with a `run_as_user_id` (whose connected accounts the run uses) and a `scope` (project or user) kept as separate axes (`models/entities.py:309-340`).

| Trigger | Mechanism | Evidence |
|---|---|---|
| Webhook | `POST /v1/hooks/{key}`; rate limit 120/min; HMAC, Stripe or Slack signature with a replay window; dedupe on delivery-id headers or body hash before dispatch; fire-and-forget or `wait=true` | `routers/hooks.py:26-190` |
| Schedule | in-process loop once a minute, leader-only; interval or cron via `croniter` | `main.py:139-210`, `services/triggers.py:146-174` |
| App event | polls a URL, extracts items, dedupes against a seen-set stored on the trigger's `meta` | `services/dispatch.py:146-230` |
| Email | inbound mail parsed into text (subject optional) through an email channel; the answer is sent back as a reply on the same thread | `channels/email.py:114-238` |

Every trigger maps its payload into a single chat message: `build_input` returns `{"messages": [{"role": "user", "content": text}]}` (`services/triggers.py:127-142`). A structured payload is serialised to JSON text inside that user message, and no typed state field receives it. That suits a chat product; a document or case workflow has to parse its input back out of a chat message.

### Versioning

Every save snapshots the workflow into `EntityVersion`, retained to a limit (default 5) and restorable (`services/versions.py:1-40`). Runs reference `workflow_id` only (`models/entities.py:263`) and compile the current executable, so a published change affects runs already in flight on resume. `subworkflow.version` is honoured only when it equals the current version; otherwise a warning is logged (`nodes/flow.py:124-133`).

## Node catalogue

Twenty-two registered types (`apps/api/forge/nodes/__init__.py:1-16`). Ports come from each `NodeSpec`; port io types are `messages`, `text`, `json`, `tool`, `embedding`, `vector`, `any`, `control` (`engine/registry.py:13-24`).

| Type | Group | In → out ports | What it does | Code |
|---|---|---|---|---|
| `start` | flow | – → control | entry marker, passthrough | `nodes/flow.py:338-350` |
| `end` | flow | control → – | wired to END | `flow.py:352-364` |
| `router` | flow | any → control (many) | sandboxed expression over state, `cases` + `default`, optional `multi` parallel routing | `flow.py:44-91,426-441` |
| `loop` | flow | any → any, may cycle | counts iterations, writes `_loop` continue/done, stops at `max_iter` or falsy `condition` | `flow.py:170-192` |
| `parallel_fanout` | flow | json → control (many) | `Send` one child per list item, stamps index and total, optional skip-on-error and per-item timeout | `flow.py:195-279` |
| `join` | flow | control (many) → json | converge; optional re-aggregation `concat`/`merge`/`first`/`last` | `flow.py:282-327` |
| `subworkflow` | flow | any → any | compile another project workflow as a nested graph; shared state by name, or isolated with `input_mapping`/`output_mapping`; recursion guard | `flow.py:99-167` |
| `agent` | agents | messages → messages, may cycle | LangChain `create_agent` ReAct loop with tools, tool sets, knowledge, MCP servers, components, middleware; can mirror a saved preset via `agent_ref` | `nodes/agent_node.py:317-405` |
| `deep_agent` | agents | messages → messages | `create_agent` plus opt-in planning, virtual filesystem, skills and sub-agents | `agent_node.py:320-370,408-421` |
| `llm` | model_tools | text → text | one model call; prompt is a `{{state.*}}` template; optional structured output to `structured_response` | `nodes/llm_node.py:20-60` |
| `classifier` | model_tools | text → text | structured-output label (or labels) into `output_key`, cheapest model by default, keyword fallback | `llm_node.py:63-205` |
| `transform` | model_tools | json → json | JMESPath (or jq) over a state key into `output_key` | `nodes/data.py:25-77` |
| `tool_call` | model_tools | json → json | invoke one materialised tool with JMESPath-mapped args; errors returned as `{error}` | `data.py:177-201` |
| `retrieval` | knowledge | text → json | RAG and Q&A lookup with hybrid, rerank, MMR, folders; injects context; optional `route_key` yes/no | `nodes/rag.py:58-194` |
| `human_input` | human | any → any | `interrupt()` approval with allowed decisions, optional input schema, timeout and default | `data.py:80-121` |
| `handoff` | human | any → any | `interrupt()` to a human inbox; the reply becomes the answer | `data.py:124-137` |
| `webhook_out` | integrations | json → json | templated HTTP call with an auth provider and SSRF check | `data.py:140-174` |
| `emit_event` | integrations | any → any | custom frame on the live stream | `data.py:204-217` |
| `webhook_in` | triggers | – → control | inbound webhook entry | `nodes/triggers.py:30-35` |
| `schedule` | triggers | – → control | interval or cron entry | `triggers.py:36-41` |
| `email_in` | triggers | – → control | inbound email entry | `triggers.py:42-47` |
| `app_event` | triggers | – → control | polling entry, once per new item | `triggers.py:48-53` |

Behaviour that is not a node in Forge lives in agent middleware (19 builders: summarisation, human-in-the-loop on tool calls, model and tool call limits, model fallback, PII, todo list, LLM tool selector, tool and model retry, tool emulator, context editing, prompt caching, moderation, dynamic model by state, tool filter by context, regex guardrail, tenant budget, semantic cache; `engine/middleware_compiler.py:556-582`) and in tools (kinds `rest`, `graphql`, `code`, `sql`, `mcp`, `builtin`, with JMESPath response projection, retries, rate limits and caching; `tools/`, `models/entities.py:77-87`).

## How a node type is defined and added

The registry docstring states the contract: "New node types are added by registering a `NodeSpec`; the compiler, the validator, and the UI palette all read from this registry without edits" (`engine/registry.py:1-5`). A `NodeSpec` (`registry.py:44-55`) carries:

| Field | Purpose |
|---|---|
| `type` | the string stored in `nodes[].type`; duplicate registration raises (`registry.py:61-65`) |
| `schema_id` | id of the JSON Schema that validates `config` (`packages/schemas/forge/nodes/*.json`) |
| `input_ports`, `output_ports` | `Port(id, io_type, direction, label, required, many)` |
| `factory(config, ctx)` | returns the LangGraph node; receives validated config and the `CompileContext` |
| `allows_cycle` | lets the validator accept cycles through this node |
| `summarize(config)` | short lines for the node body |
| `category`, `label`, `description` | palette grouping and text |

`GET /v1/node-types` serves the registry to the console (`routers/nodes.py:24-38`), which groups the palette by category (`apps/web/components/screens/workflows.tsx:690-694`) and colours handles by io type (`apps/web/components/canvas/ForgeNode.tsx:56-80`). The JSON Schemas carry `x-ui` hints (widget, section, help, `refType` for references) intended for a generated form (`packages/schemas/forge/workflow.json:13`, `nodes/tool_call.json`).

In practice, adding a node needs edits in more places than the docstring claims. Per-type knowledge sits in:

| Place | What it hard-codes |
|---|---|
| `services/validation.py:249-347` | which config field each type writes to state, and the values it can write, for router and undeclared-write checks |
| `apps/web/lib/graph.ts:83-93` | the same written-keys table, again, to auto-declare state on save |
| `apps/web/lib/data.ts:24-57,89+` | palette icons, labels, groups and hover help (`NODE_CATALOG`, `NODE_HELP`) |
| `apps/web/components/canvas/ForgeNode.tsx:17-48` | a second `summarize` switch; the backend `summarize` is not sent by `/v1/node-types` (`routers/nodes.py:26-37`) |
| `apps/web/components/screens/workflows.tsx:1070-1141` | hand-written inspector fields (`NODE_FIELDS`); no file under `apps/web` mentions `SchemaForm` or `x-ui`, so the schema hints are not rendered, although `README.md` describes a `<SchemaForm>` |
| `engine/compiler.py` | special cases for `end`, `router`, `parallel_fanout`, `deep_agent` |

The drift is visible. The `transform` inspector says its expression is a "Sandboxed expression over state (e.g. len(messages))" (`workflows.tsx:1074`), while the node runs JMESPath (`nodes/data.py:57-77`). The `tool_call` factory reads `output_key` (`data.py:180`) but its schema has no such field and does declare `handle_tool_errors`, which the factory ignores (`packages/schemas/forge/nodes/tool_call.json`). The lesson for Ops AI: the node spec must own every fact other layers need (written state keys and their value sets, summary, help text, form hints), and the other layers must read it, otherwise each new type costs five edits and they drift.

## Data mapping and expressions

Forge uses three small languages and says so (`engine/expressions.py:1-14`):

| Language | Used for | Evidence |
|---|---|---|
| RestrictedPython expressions | decisions: router `expression`, loop `condition`, edge `condition`, some middleware; state keys are bare names, plus `state` and `context`; safe builtins only | `engine/expressions.py:23-62` |
| JMESPath (optionally jq) | extraction and reshaping: `transform`, `tool_call.input_mapping`, tool `projection_jmespath`, trigger `message_path`, app-event `items_path` | `nodes/data.py:57-77,189-194`, `services/triggers.py:133-137` |
| `{{a.b}}` templates | building strings and bodies: `llm.prompt` (`{{state.x}}`), `webhook_out` url/body/headers, `emit_event` payload, tool requests (`{{input.*}}`, `{{ctx.*}}`, `{{env.*}}`, `{{cred.*}}`); a whole-string token keeps its native type; `$each`/`$as`/`$do` builds arrays; `env` is strict and raises on a missing key | `auth_providers/templates.py:1-80` |

Data moves between nodes only through named state keys. Data nodes read an optional `input_key` and write an `output_key` that must be declared in `state`, or LangGraph drops the write silently; the validator turns that into an error (`nodes/data.py:1-9`, `services/validation.py:350-363`) and the canvas auto-declares known output keys (`apps/web/lib/graph.ts:79-113`). There is no per-edge mapping and no typed output schema per node: ports carry an io type for wiring hints, but the payload is whatever the node writes to state.

## Credentials

Secrets are encrypted rows referenced as `secret://proj/<name>`; the ref carries only a name, tenant and project scope come from the caller, and every read is audited at the store (`secrets/store.py:1-8`). Auth providers (bearer, API key, basic, OAuth2 client-credentials and three-legged, CSRF/session) resolve headers, params and cookies for tools and `webhook_out` (`nodes/data.py:158-164`). Per-request secrets from the caller travel in `run_context`, which is never persisted or shown to the model (`engine/context.py:67-75`). Provider API keys come from project secrets into `ctx.provider_credentials` (`engine/models.py:101-108`).

## Editor and how nodes are shown

| Feature | Evidence |
|---|---|
| React Flow canvas; node is a card with io-type-coloured handles, a title and two summary lines | `apps/web/components/canvas/ForgeNode.tsx` |
| Palette from the registry, grouped by category, with hover help and an example per node | `workflows.tsx:690-694`, `lib/data.ts:89+` |
| Canvas ↔ executable translation in the browser: entry is the start node, else a trigger, else a node with no incoming edge; router cases are taken from labelled edges | `apps/web/lib/graph.ts:95-157` |
| Save stores canvas and executable even when invalid; validation returns JSON-pointer errors and warnings so the UI can jump to the field | `services/workflows.py:109-125`, `services/validation.py:25-38` |
| Warnings for likely wiring bugs: router without default, router on a key nothing writes, case keys that can never match, dead-end nodes, io-type mismatch, webhook requiring a signature with no secret | `services/validation.py:181-243,270-321` |
| Test panel and a live overlay that lights nodes as the run streams; per-node token and cost roll-up from trace spans | `components/canvas/WorkflowTestPanel.tsx:16`, `services/runs.py:323-357` |
| Version history with restore | `components/version-history.tsx:27`, `services/versions.py:1-40` |
| Import and export as `forge.bundle/1` JSON with secret values stripped | `services/portability.py:44-127`, `docs/ROADMAP.md:45` |
| An in-product assistant that builds workflows: lists node types, reads a node schema, creates a custom workflow from JSON (validated), and has template builders (`create_grounded_workflow`, `create_intent_router_workflow`, `add_human_review`), a test runner and a self-check | `services/assistant.py:135-760` |
| Starter templates in the UI: `starterWorkflow` and `groundedWorkflow` | `apps/web/lib/graph.ts:159-191` |

## Comparison with Ops AI

Ops AI paths are under `packages/ops_engine/src/ops_engine/` unless stated; the planned column comes from [workflow nodes](../workflows/workflow-nodes.md) and [workflow runner](../../architecture/workflow-runner.md). Ops AI was read at commit `96e9022`.

| Concern | Forge | Ops AI today | Ops AI planned | Take, adapt or skip |
|---|---|---|---|---|
| Engine | LangGraph `StateGraph`, compiled per run (`engine/compiler.py:76-188`) | LangGraph `StateGraph` (`compiler.py:440-472`) | same | Same base; nothing to take |
| Type contract | `NodeSpec`: type, schema id, ports with io type, factory, `allows_cycle`, summarize, category (`engine/registry.py:44-55`); no version | `NodeType`: id + integer version, group, ports with connection type, parameters JSON Schema, effects, retry, executor name, timeout, `outputs_from` (`node_types.py:58-106`) | add sub-node connection types `model`, `tool`, `knowledge`, `memory` | Keep ours; it is richer. Adapt: add the facts Forge scattered across five files (written keys, summary, help, form hints) to `NodeType` so the editor and validator never keep a second list |
| Executor binding | factory closure per node, receives `CompileContext` | executor string → `EXECUTORS` dict (`compiler.py:266-276`); each receives a `NodeCall` with ports | same | Keep ours; a registry check that every `executor` names a key in `EXECUTORS` would close the one gap |
| State model | shared named keys with reducers; writes to undeclared keys are dropped (`engine/state.py:43-63`, `services/validation.py:350-363`) | one channel per node holding `{port, stepId, iteration, out}` plus `input` (`compiler.py:1-5,449-450`) | outputs over 8 KB moved to the journal | Keep ours. Per-node envelopes remove Forge's whole class of "undeclared key" and "nothing writes this key" bugs that its validator spends four checks on |
| Data mapping | JMESPath for reshaping, `{{a.b}}` templates for strings, RestrictedPython for decisions (`engine/expressions.py:1-14`) | `$.input.x` / `$.nodes.<id>.out.x` path values, resolved recursively in parameters (`compiler.py:80-108`) | `ops.data.set` general mapping, `ops.data.code` later | Adapt: add one reshaping language (JMESPath) for lists and projections, and string templates for prompts and message bodies. Skip RestrictedPython: Ops AI's structured conditions are safer and editable as a form |
| Conditions | expression string evaluated over state (`nodes/flow.py:44-91`) | `left`/`op`/`right` rules with `all`/`any` (`node_types.py:149-157,192-210`) | `ops.flow.switch` | Keep ours; take Forge's `multi` (route to every matching case in parallel) for `switch` |
| Branching | router `cases` + `default`; edge `branches` + `condition` | out ports on every node; unconnected out port fails publish (`definition.py:240-244`) | review options and tool outcomes as ports | Keep ours; ports make the default path explicit, which Forge only warns about (`services/validation.py:276-284`) |
| Loops | `loop` counter node + router back edge; cycles allowed only through `allows_cycle` types; recursion budget derived from graph size and `max_iter` (`services/runs.py:380-395`) | none; recursion limit fixed at 100 (`worker.py:39,72`) | `ops.flow.loop` as for-each with join; "retry loops through If and Loop" (`workflow-nodes.md`, changed types) | Adapt: derive the recursion limit from the definition the way Forge does once loops exist, and add `allows_cycle` (or equivalent) to the validator before any back edge is allowed |
| Parallel map and join | `Send` per item with index and total, `add` reducer, optional skip-on-error and per-item timeout (`flow.py:195-279`) | none | `ops.flow.loop` each/done, `ops.flow.merge` | Take the index stamping and per-item isolation; Ops AI's journal key already carries `iteration`, so add an item index to it |
| Retries | whole-run retry ×3 in the worker; tool-level retries for idempotent HTTP; agent middleware retries (`worker.py:25-67`, `tools/rest.py:94-110`) | per-node attempts by effects class with backoff; writes never resent, reconciled by key (`compiler.py:290-416`, `node_types.py:49-55`) | same | Keep ours; Forge has no node-level idempotency, and its run retry restarts the graph |
| Timeouts | global run wall clock; per-item fan-out timeout; schema `timeout_seconds` unused | per-attempt timeout by type, overridable per node (`node_types.py:73-74`, `compiler.py:366`) | Wait node, review SLA via `TimerPort` | Keep ours. Skip Forge's unwired fields as a pattern to avoid |
| Persistence and resume | checkpointer + run row; reaper for stale runs; durable SSE broker (`services/runs.py`) | journal rows per attempt, Postgres queue with `SKIP LOCKED`, leases with fencing (`store/work.py:1-70`, `worker.py`) | 200 concurrent runs on two workers | Keep ours; take the stale-run reaper rules (queued too long, running too long) if Ops AI's sweeper lacks them |
| Human steps | `human_input` interrupt with allowed decisions, input schema, timeout and `timeout_default`; `handoff` to an inbox (`nodes/data.py:80-137`, `services/runs.py:1183-1300`) | `ops.flow.humanReview` with options as ports, per-option inputs and an approved write (`node_types.py:265-322`, `compiler.py:201-242`) | SLA, approvers, step-up | Keep ours; take `timeoutDefault` (resume with a named option when the SLA expires) |
| Triggers | webhook (signature schemes, replay window, delivery-id dedupe), schedule (interval, cron, leader-only), email, polling app event with seen-set; every payload becomes one chat message (`routers/hooks.py`, `services/triggers.py:127-174`) | `ops.trigger.request` with an `inputSchema` (`node_types.py:160-173`) | email, chat, schedule, batch, workflow | Take the webhook signature and dedupe rules and the polling trigger; skip the payload-as-chat-message mapping, Ops AI's typed `payload` port is better for cases |
| Sub-workflows | nested compiled graph, shared or mapped keys, recursion guard, version pin best-effort (`flow.py:99-167`) | none | `ops.action.workflow` continue or wait, `ops.trigger.workflow` with typed inputs | Keep the plan; take Forge's recursion guard idea as a publish check (a workflow cannot start itself through a chain) |
| AI steps | `agent`, `deep_agent`, `llm`, `classifier`, `retrieval`; classifier defaults to the cheapest model (`nodes/llm_node.py:63-87`) | `ops.ai.agent` through `AgentPort.turn` with output schema (`node_types.py:239-264`) | classify, extract, summarise, score, answer | Take the cheap-model default for classify and score; take the keyword fallback only as an explicit `fallback` port that the author wires |
| Tools | six tool kinds with JMESPath response projection, retries, cache (`models/entities.py:77-87`, `tools/`) | every call through the tools-service gateway (`ops.action.tool`) | sub-node `ops.tool.operation` | Keep ours; consider response projection at the gateway so large tool outputs do not bloat the journal |
| Credentials | `secret://` refs, encrypted, audited at the store; auth providers; per-run `run_context` never persisted (`secrets/store.py:1-8`, `engine/context.py:67-75`) | approval tokens redacted from the journal (`compiler.py:419-429`); credentials live behind the gateway | – | Keep ours; take the rule that per-request caller secrets never enter state, journal or prompt |
| Versioning | snapshots per save, 5 kept, restore; runs use the current executable (`services/versions.py`, `models/entities.py:263`) | immutable versions by digest; runs pin version and digest; compiled graphs cached by digest (`store/definitions.py:1-60`, `store/runs.py:38-51`, `compiler.py:475-492`) | type version pinned per node; migrate a paused run | Keep ours; Forge's approach lets an edit change a paused run |
| Validation | schema + per-node schema + structure + heuristic warnings with JSON pointers (`services/validation.py`) | duplicate ids, unknown type or version, parameter schema, unknown references, unknown or unconnected ports, approval order, reachability (`definition.py:184-258`) | – | Take the warnings layer: router-style "this case can never match", dead ends, signature without secret. Add an ancestor check: a `$.nodes.X` mapping should read a node upstream of the reader |
| Editor | React Flow, registry palette by category, io-coloured handles, hand-written forms, live run overlay, per-node cost (`apps/web/components/canvas/*`) | v2 editor: registry palette (`definition-editor/type-palette.tsx`), parameters as a raw JSON textarea (`node-inspector.tsx:106-117`); older 28-kind display-only palette (`apps/console/src/components/workflows/node-types.ts:87-133`) | – | Adapt: render the inspector from each type's JSON Schema plus UI hints, which Forge planned and never built |
| Debugging | test panel, live overlay, per-node tokens and cost from spans (`services/runs.py:323-357`) | each run shows every step with input, output and port | pins, retry a step, run from a node, replay check | Ours is ahead in plan; take per-node cost roll-up |
| Authoring by AI | assistant with `list_node_types`, `get_node_schema`, `create_custom_workflow` (validated), templates, test and self-check (`services/assistant.py:135-760`) | none | – | Take: it is the cheapest way to cover many use cases (see below) |
| Portability | `forge.bundle/1` JSON export and import, secret values stripped (`services/portability.py:44-127`) | YAML or JSON definitions (`definition.py:1-15`) | – | Take bundles with dependencies (agents, tools, knowledge refs) for templates |
| Error handling | `on_error` fallback message; `error_policy` mostly unwired | error port where the type has one, else the run fails (`compiler.py:385-389`) | `ops.flow.stop`; console "On error" path in the old palette | Adapt: a workflow-level error route to a named node, wired end to end before it appears in the schema |

## Nodes worth adding

A node is listed only when it uses one of Ops AI's ports ([workflow runner](../../architecture/workflow-runner.md) §2) or needs no outside call.

| Node | From Forge | Uses | Notes |
|---|---|---|---|
| `ops.trigger.poll` | `app_event` (`nodes/triggers.py:48-53`, `services/dispatch.py:146-230`) | `TimerPort` for the interval, `ToolPort.call` for the read, a seen-set keyed by an item path | Turns any list endpoint (a queue, a mailbox API, a ledger) into one run per new item; the read goes through the gateway so it is audited |
| `ops.trigger.schedule` options | `schedule` interval or cron (`services/triggers.py:146-168`) | `TimerPort` | Planned already; take cron plus interval and leader-only firing |
| Request trigger signing | webhook signature schemes and dedupe (`routers/hooks.py:26-150`) | none | Parameters on `ops.trigger.request`: `signatureScheme`, `secretRef`, `toleranceSeconds`, `dedupeHeader`, `dedupeBody` |
| `ops.data.transform` | `transform` (`nodes/data.py:57-77`) | none | JMESPath over a mapped input; effects none. Keeps `ops.data.set` for renames and covers filter, flatten, project, count |
| `ops.data.template` | `{{…}}` templates (`auth_providers/templates.py`) | none | Renders a string or JSON body from mapped values, with `$each` for lists; feeds Send, prompts and tool bodies |
| `ops.flow.switch` with `multi` | router `multi` (`nodes/flow.py:44-91`) | none | Planned; add the option to take every matching port in parallel |
| `ops.flow.repeat` (while or until) | `loop` (`flow.py:170-192`) | none | The planned loop is for-each only; retry-until-score-passes needs a bounded while loop and the derived recursion limit |
| `ops.flow.merge` reducers | `join` (`flow.py:282-327`) | none | Planned; take `concat`, `merge`, `first`, `last` and ordering by item index |
| Review timeout default | `human_input.timeout_default` (`nodes/data.py:93-98`) | `TimerPort`, `ReviewPort` | Parameter on `ops.flow.humanReview`: the option taken when the SLA expires; empty means the expiry port |
| `ops.ai.classify` defaults | `classifier` (`nodes/llm_node.py:63-187`) | `AgentPort` or a model port | Planned; take the cheap-model default and a bounded recent-context window |

Skipped, with reasons: `webhook_out` (every outside call in Ops AI goes through the tools gateway as `ops.action.tool`), `emit_event` (`EventPort` already streams step events), `deep_agent` and sub-agent folding (an agents-service concern behind `AgentPort`), `retrieval` as a context-injecting node (`ops.ai.answer` on `KnowledgePort` is planned and returns citations), `handoff` (Ops AI's review and case model covers it).

## Supporting hundreds of use cases

Forge ships 22 node types and covers its use cases mainly through tools (six kinds), 19 agent middleware builders and templates; the node catalogue stays small. That is the main lesson: variety should come from configuration of a few generic nodes, and new node types should be rare.

| Idea | Evidence or gap |
|---|---|
| Keep the node catalogue small and generic; put integrations in tools behind `ops.action.tool` | Forge's variety lives in tool kinds and middleware (`models/entities.py:77-87`, `engine/middleware_compiler.py:556-582`); Ops AI's gateway already gives every operation one node |
| One type contract that owns every fact: ports, parameter schema, UI hints, help, example, written outputs, summary line | Forge's five-file drift (`services/validation.py:249-347`, `apps/web/lib/graph.ts:83-93`, `ForgeNode.tsx:17-48`, `workflows.tsx:1070-1141`, `lib/data.ts`) and the `transform` help text that describes the wrong language (`workflows.tsx:1074`) |
| A schema-driven inspector: render parameters from JSON Schema with widget hints (`reference` to a tool, agent, knowledge base or workflow; `rows-table`; `textarea`; model picker) | Forge's schemas carry `x-ui` hints that nothing renders; Ops AI's inspector is a JSON textarea (`node-inspector.tsx:106-117`) |
| A node SDK: a documented `NodeType` + executor pair, a test helper that runs one node against fake ports, and a registry check that each executor exists | Forge's contract is one `register(NodeSpec(...))` call (`engine/registry.py:61-65`); ours needs a `NodeType` and an `EXECUTORS` entry (`compiler.py:266-276`) with no check linking them |
| Templates as versioned bundles: a definition plus the agents, tool grants and knowledge refs it needs, installable into a team | Forge's `forge.bundle/1` export and its UI and assistant templates (`services/portability.py:44-127`, `apps/web/lib/graph.ts:159-191`, `services/assistant.py` `create_grounded_workflow`) |
| Patch templates that add a pattern to an existing workflow, such as "add a review before this write" | Forge's `add_human_review` assistant tool (`services/assistant.py:518-560`) |
| An authoring assistant that reads the registry and schemas, writes a definition, validates it and test-runs it on the fake model | Forge's assistant tools `list_node_types`, `get_node_schema`, `create_custom_workflow`, `test_workflow`, `evaluate_build` (`services/assistant.py:561-697`); Ops AI's fake model port makes the test run free |
| Validation warnings written for authors, each pointing at a field | Forge's warning catalogue with JSON pointers (`services/validation.py:181-243`); Ops AI's checks are structural only (`definition.py:184-258`) |
| Typed trigger payloads, with input schemas, so a case workflow never parses a chat message | Forge maps every trigger to a user message (`services/triggers.py:127-142`); Ops AI's request trigger already has `inputSchema` |
| Never ship a definition field the runner does not read | Forge's `route_to_error_node`, `timeout_seconds`, `max_concurrency` (`packages/schemas/forge/workflow.json:22,31-32`) are read by no Python file |
| A fake model and offline test suite for every node type | Forge runs its engine tests with `fake:` models and no keys (43 passed); Ops AI's fake model port does the same job and should cover every new type |

## Open questions

| Question | Why it matters |
|---|---|
| What recursion limit do loops need? `RECURSION_LIMIT = 100` is fixed in `worker.py:39`. A for-each built on `Send` uses few supersteps, but a retry-until loop through If spends several per pass | Forge hit LangGraph's default of 25 after about eight loop iterations and now derives the limit (`services/runs.py:380-395`) |
| Does `ops.data.set` stay a pure rename, or does it absorb JMESPath reshaping? | Two nodes are clearer for authors; one node means fewer types. Assumption in this doc: two nodes |
| Should trigger dedupe live in the trigger or in the queue's dedupe key? | `engine_work` already has one row per dedupe key (`store/work.py:33`); Forge dedupes in an in-memory or Redis cache before dispatch (`routers/hooks.py:168-175`) |
| Where do UI hints for parameters live: inside the JSON Schema (`x-ui`) or as a sibling field on `NodeType`? | Forge put them in the schema; a sibling keeps the schema valid for strict validators |
| Who may publish a new node type, and do third-party types run in-process? | Forge types are in-process Python; hundreds of use cases will tempt per-customer types, which Ops AI's standards gate would need to cover |
| Should `$.nodes.X` mappings be restricted to ancestors of the reading node? | Neither validator checks it today; a read of a node on another branch returns None at run time (`compiler.py:80-91`) |
