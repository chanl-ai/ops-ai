# The API

Status: current, updated 2026-10-11 against HEAD; every decision is an option until the owner confirms it.

## Decisions

| Decision | Detail |
|---|---|
| One API for chat and workflows | Six families, 54 calls. Four do the work: create a thread, run it, read its state, decide a review |
| Versions move only through the pointer | Deployments name `wf_d@production`; `POST …/pointer` moves it; rollback is the same call; running threads keep their version |
| Decide is the only door for a policy-owned pause | `POST /v1/reviews/{id}/decide` resumes it; a resume sent to `runs` answers 409. A plain question to a chat user, owned by no policy, may resume through `runs` | Chat approvals use the same door: the chat widget action calls decide.
| Knowledge, tools, connections, files, sign-in and settings | Their own families; not in this page |

## Calls

"In code" counts a call that exists with the designed shape; "partial" exists under another route or with a
narrower shape; "proposed" has no code. Count: 5 in code, 17 partial, 32 proposed, of 54.

| Family | Call | What it does | State |
|---|---|---|---|
| Agents | `GET /v1/agents`, `POST /v1/agents` | List; create a draft | In code: registry rows (`api/agent_registry.py`); the seed agents are rows, published at their seed version. An agent may name a model alias: a publish request naming one models-service does not serve (or, without models-service, anything but the runtime's alias) answers 422 `unknown_model_alias`; an agent with none runs on the runtime's alias, and the test turn reports which it used |
| Agents | `GET /v1/agents/{id}`, `PATCH /v1/agents/{id}`, `DELETE /v1/agents/{id}` | Read; save a new draft version; delete | In code. A save never changes what is live |
| Agents | `POST /v1/agents/{id}/test` | One turn of the draft, no thread kept | In code; a write tool stops at its gate and the reply carries `wouldPause` |
| Agents | `POST /v1/agents/{id}/publish-requests` | Open an `agent_publish` review for the newest draft | In code. Dev `registry_auto_approve` approves it at once: the version goes live and `agent:<id>` joins `GET /v1/graphs`. Outside dev it stays pending until `POST /v1/publish-requests/{id}/decision` |
| Agents | `GET …/versions`, `POST …/versions/{n}/restore` | History; restore into a new draft | In code |
| Agents | `POST /v1/agents/{id}/paused` | Stop or resume new threads | In code. The pointer moves only by publishing; a restore plus publish moves it back |
| Agents | `GET /v1/tools` | The tools an agent can be granted: id, description, access class, approval template | In code on agents-service, from the runtime catalogue; moves to tools-service with the catalogue |
| Agents | `GET /v1/model-aliases` | The chat aliases an agent may name: name, kind, clearance and prices; exactly the set a publish request accepts | In code on agents-service: models-service's chat aliases when it is configured, else the runtime's own alias by name |
| Agents, Workflows | `GET /v1/publish-requests/{id}`, `POST /v1/publish-requests/{id}/decision` | Read or decide an agent or workflow publish request: approved, rejected or returned, with a reason for the last two | In code. The requester cannot decide, nor can the person who saved an agent version; approving publishes what the request recorded |
| Workflows | `GET /v1/workflows`, `POST /v1/workflows`, `GET`/`PATCH`/`DELETE /v1/workflows/{id}` | List; create from a template; read with live graph and draft; settings; delete | In code (`api/workflow_registry.py`). The id is the graph name for `POST /v1/threads`. dispute_email and wire_hold_review are seeded live |
| Workflows | `PUT …/draft`, `DELETE …/draft` | Save or discard the canvas graph | In code; the draft is read on `GET /v1/workflows/{id}` |
| Workflows | `POST …/validate`, `GET …/validations/latest`, `POST …/test` | Compile checks: node types, agent pins, one trigger, reachability; run once in memory with pauses approved | In code. Branch and router nodes with more than one route fail checks: no rule chooses between them yet |
| Workflows | `POST /v1/workflows/{id}/publish-requests` | Compile to a definition with digest, pin agents, open a review | In code. Agent steps copy the published agent definition into the node, so the digest pins it. Dev `registry_auto_approve` publishes at once |
| Workflows | `GET …/versions` | Version history | In code |
| Workflows | `POST …/versions/{n}/restore`, `POST …/pointer`, `POST …/status` | Restore into the draft; move the pointer; live or paused | In code. New threads start on the pointer; paused answers 409 `workflow_paused` |
| Workflows | `GET /v1/workflows/{id}/runs` | Threads this workflow ran | In code, steps from each thread's run journal |
| Deployments | `POST /v1/deployments` | One row: pointer, channel, environment, settings | Partial: graph name, channel, multitask, paused, default `budget`; no pointer or environment |
| Deployments | `PATCH /v1/deployments/{id}`, `…/pause`, `…/resume` | Change settings; stop or restart new threads | Partial: `PATCH` sets `paused` only |
| Deployments | `GET /v1/deployments`, `GET …/{id}`, `DELETE …/{id}`, `GET …/traffic` | List, read, remove, traffic numbers | Proposed |
| Threads | `POST /v1/threads` | Find or create by `externalKey`; store the version the pointer names | In code, with an optional `budget` (`maxCalls`, `maxTokens`, `maxCost`) that falls back to the deployment's; 429 `key_budget_exhausted` when the caller's key is over its budget (the port admits every key today) |
| Threads | `GET /v1/threads` | List with filters | Partial: `graph` filter only |
| Threads | `POST /v1/threads/{id}/runs/stream` | Run with input or resume; stream events | In code, without `multitask` (a busy thread answers 409); a review- or approval-owned interrupt answers 409 `resume_via_review` |
| Threads | `POST /v1/threads/{id}/runs` | Run without streaming | Proposed (`GET` on this path returns the run journal) |
| Threads | `GET /v1/threads/{id}/state` | Status, values, pending interrupt, next node, version, digest, SLA | In code, plus `cost` (`calls`, `inputTokens`, `outputTokens`, `cost`, summed from usage rows) and `budget` (`maxCalls`, `maxTokens`, `maxCost`) |
| Threads | `PATCH /v1/threads/{id}/state` | Edit state while waiting, journaled | Proposed |
| Threads | `GET /v1/threads/{id}/history` | Every step with inputs and outputs by reference | Partial: `GET /v1/threads/{id}/runs` lists runs and node sequences |
| Threads | `GET …/runs/{runId}/events?after=seq` | Re-attach from the stored event log | In code: SSE of the stored events in the designed shape, `seq` above `after`; `follow=false` returns what is stored and closes |
| Threads | `POST …/cancel` | Cooperative stop | Proposed |
| Threads | `POST /v1/threads/{id}/route-to-people` | Hand remaining steps to people | In code for definition workflows; a code graph answers 409 `not_routable` ([durability-failure-and-audit.md](durability-failure-and-audit.md#side-effect-classes)) |
| Threads | `POST /v1/threads/{id}/migrate` | Move a waiting thread to a newer version | In code |
| Threads | `PATCH /v1/threads/{id}`, `DELETE /v1/threads/{id}` | Title, pin, archive; hide | Partial: on `/chat/threads`, which stores title, pin, archive and hide in the agent_wrapper thread's metadata |
| Threads | `PUT …/messages/{mid}/feedback` | Thumbs and a note | Partial: on `/chat/threads`; stored as a `feedback` thread event, latest wins |
| Reviews | `POST /v1/reviews/{id}/decide` | Approve, reject or answer, with reason and step-up | Partial: `POST /reviews/{threadId}/decision` records the decision, then resumes; it is the only way to resume a review-owned step; it mints the approval token itself and emits `decided`|
| Reviews | `GET /v1/reviews`, `GET /v1/reviews/{id}` | The queue; one item with its evidence | Partial: `GET /reviews`, `GET /reviews/{threadId}`, on the console's contract |
| Reviews | `POST /v1/reviews/assign`, `POST /v1/reviews/bulk-decide` | Assign; decide many, one token each | Partial: `POST /reviews/assign`, `POST /reviews/bulk-decision` |
| Reviews | `GET /v1/review-policies` | Read pinned policies | Proposed |
| Streams | `GET /v1/events` | SSE of thread events for the caller's team, `after=seq` | In code: SSE per caller team, lifecycle types (`started`, `waiting`, `waiting_review`, `decided`, `finished`, `failed`) as `thread.<type>`; the SSE `id` is the position for `after` |
| Webhooks | `POST`, `GET /v1/webhooks`, `DELETE …/{id}`, `POST …/{id}/test` | Standard Webhooks signing, retried 72 hours, at least once | Proposed |

## Routes in code that are not in the design

| Route | Service | Why it exists |
|---|---|---|
| `/chat/*` and `/v1/chat/*` (11 routes) | The console chat, as a facade over the thread calls: a conversation is an `agent_wrapper` thread, a message is a leased run streamed as `ChatStreamEvent`, an approval is decided through `POST /reviews/{id}/decision`, and messages are rebuilt from run inputs and `thread_events`. Its own tables are dropped by migration 0017. Marked for removal under console strategy rule 6: it exists only until the chat page speaks the thread calls through the SDK | The console chat, on its own tables, calling the kernel directly. Moves onto the thread calls when chat runs as the `agent_wrapper` graph |
| `POST /v1/threads/{id}/approvals` | agents-service | Records an approver for the exact call the thread waits on and mints the token once enough approvers exist; the decide path calls it. It has no requester check |
| `POST /v1/threads:route-to-people` | agents-service | Routes every open thread of one workflow version to people |
| `POST /v1/auth/step-up` | agents-service | Dev sign-in's step-up: re-checks the password (and code) and returns a signed step-up token for the caller, valid five minutes ([identity-and-tenancy.md](identity-and-tenancy.md#approval-and-step-up-token-facts)) |
| `/runs/*`, `/reviews/*` (7 routes) | agents-service | The console's Cases and Reviews contract served from runtime threads (`api/hitl_facade.py`) until hitl-service exists; rows arrive pre-joined with state, journal, SLA and decisions |
| `POST /v1/threads/{id}/events` | agents-service | `customer_reply`: restarts the SLA clock |
| `POST /v1/threads/{id}/timers/{timerId}/fire` | agents-service, internal | The only way a timer fires; service token ([human-in-the-loop.md](human-in-the-loop.md)) |
| `POST`, `GET /v1/threads/{id}/inbox` | agents-service | Queued channel input for a busy thread ([channels-and-deployments.md](channels-and-deployments.md)) |
| `POST /v1/calls`, `POST /v1/fences` | tools-service | A tool call through policy; raising the fence at takeover |
| `GET /health` | both | Liveness |

## Request conventions

| Convention | Rule | In code |
|---|---|---|
| Envelope | `{success: true, data}` or `{success: false, error: {code, message, status, requestId, details?}}` | Yes, `ops_agents/api/envelope.py` |
| OpenAPI | Every operation has an operationId (`<tag>_<handler>`), one tag per family above, the error envelope on every status, and a typed success response. The document is committed as `services/agents-service/openapi.json`; a generated SDK is built from it | In code: every operation is typed, and `openapi-untyped.txt` is empty. `make openapi-check` fails on drift, a repeated or missing id, a bare request body, or an untyped route. The API tests validate every response against the document (`tests/contract.py`). The chat facade is left out |
| Errors | 400 `validation_failed`, 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 409 conflicts by code, 422 `step_up_required` or `approval_token_required`, 429 `key_budget_exhausted`, 500 `internal` | Yes |
| Conflict codes | `run_active` (with owner, runId, ageSeconds), `run_waiting`, `run_not_waiting`, `not_waiting`, `node_missing`, `deployment_paused`, `nothing_to_approve`, `already_decided` (a different decision on a decided review), `digest_mismatch` (the pinned version's stored digest no longer matches), `no_sla_waiting` (a customer reply to a thread with no SLA step waiting), `not_routable`; tools-service `lease_superseded`, `write_in_progress` | Yes |
| Idempotency | Every write takes a key kept in our own dedupe table. A repeated `runId` replays the stored events instead of running again; a repeated `externalKey` returns the existing thread; a repeated tool write returns the first result | Run id and external key: yes. A general `Idempotency-Key` header: proposed |
| Paging | Cursor paging with the usual filters on every list | Proposed; lists return everything |
| Team | From identity, never from a parameter | Not yet: the dev principal reads `X-Team-Id` ([identity-and-tenancy.md](identity-and-tenancy.md)) |
| Auth on internal routes | Bearer service token; workload identity in a deployment | Shared token in code |

## Event schema

Every stream, webhook and adapter uses one thread event. Receivers dedupe on `id`.

| Field | Designed | In code |
|---|---|---|
| Shape | `{id, seq, type, threadId, runId, node, at, data}` | Designed shape in `thread_events` and the read routes; `runs/stream` still sends `{event, runId, seq, node?, data?}` for one release (deprecated) |
| `seq` | Rises by one per thread | Per thread in the log; per run in the old stream |
| Types | `started`, `node`, `text`, `tool_call`, `citation`, `widget`, `waiting`, `waiting_review`, `decided`, `finished`, `failed`, `cancelled` | `started`, `node`, `tool_call`, `text`, `waiting`, `waiting_review`, `decided`, `finished`, `failed`, plus custom node events |
| Storage | An event log written as events happen, read by re-attach and webhooks | `thread_events` (migration 0015), written as events happen on PostgreSQL (one INSERT…SELECT each) and at run end on SQLite; `graph_runs.events` is still written at run end |
| Transport | SSE (`sse-starlette`), ping every 15 s | Yes |

Stream re-attach and first-byte timing cannot be tested with an in-process ASGI transport, which buffers the whole
response ([chat-turn-latency](../services/agents-service/experiments/chat-turn-latency.md)); use a real server.
