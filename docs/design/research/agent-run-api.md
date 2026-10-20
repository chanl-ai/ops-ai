# Agent run API: prior art

Status: research note; sources as fetched in October 2026. Claims carry the URL they came from; anything marked
"inferred" is drawn from the docs without a direct statement to quote.

Do agent platforms build chat as a layer over a lower-level agent run API, and how do they run an agent with no chat at
all (triggers, schedules, background and long runs, goals, human approval)? Ops AI needs an answer because its agents
run independently of the workflow runner, and chat, scheduled jobs and workflow steps all need one way to start an
agent and read what it did. This note compares eight platforms and ends with the run API the comparison points to.
How agents and workflows fit together is in [workflows and agents](../workflows/workflows-and-agents.md); the runtime
as built is in [inside the runtime](../../architecture/runtime.md).

## Ops AI when this was written

| Piece | What exists | Source |
|---|---|---|
| Chat | `POST /threads`, `POST /threads/{id}/messages` (streamed), thread CRUD; each thread runs on the agent's own LangGraph graph with a checkpointer and a lease | `services/agents-service/src/ops_agents/api/routers/chat.py` |
| Events | `GET /v1/threads/{thread_id}/runs/{run_id}/events` and `GET /v1/events` as SSE, re-attach with `after=seq` | `routers/events.py`, [workflow runner](../../architecture/workflow-runner.md) section 5 |
| Approvals | `POST /{thread_id}/approvals`; a write tool raises a LangGraph interrupt and the thread waits | `routers/` approvals route, `docs/console/agents-and-workflows.md` |
| Workflow runs | `POST /v1/runs` returns 202, Postgres queue `engine_work`, workers, journal; agent node calls `AgentPort.turn(request)` | [workflow runner](../../architecture/workflow-runner.md) |
| Agent test | `POST /v1/agents/{id}/test` runs one stateless turn | `routers/agents.py` |

The gap the research addresses: there is no agent run resource of its own. A chat turn is the only way to run an agent
outside a workflow, and the workflow agent node calls the kernel through a port.

## 1 Relevance AI

Relevance AI is the closest product to the "full agentic" Ops AI edition. Its core unit is the **task**: "A Task is a
single run of work carried out by an Agent or a Workforce: a conversation with an Agent, or a workflow a Workforce runs"
([task overview](https://relevanceai.com/docs/build/agents/give-your-agent-tasks/task-overview.md)). The SDK says the
same from the other side: a task is "a single conversation thread between your application and an agent or workforce"
([SDK tasks](https://relevanceai.com/docs/sdk/tasks.md)). So in Relevance a conversation and a run are one object.
There is no separate run inside a task; each new message re-activates the same task.

### Resources

| Resource | What it is | Source |
|---|---|---|
| Agent | Prompt, model, tools, subagents, triggers, approval settings per tool | [SDK agents](https://relevanceai.com/docs/sdk/agents.md) |
| Task (also called conversation; id is `conversation_id`) | One thread of work with an agent or a workforce; holds messages, status and steps | [SDK tasks](https://relevanceai.com/docs/sdk/tasks.md), [API trigger](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/api-trigger.md) |
| Message | User, agent, tool (with its own status), thinking, typing, error, workforce handover | [SDK messaging](https://relevanceai.com/docs/sdk/messaging.md) |
| Step | The tool and model steps inside a task, read with `view_steps` | [API listing on jentic](https://jentic.com/apis/relevanceai.com/relevanceai.md) |
| Trigger | Integration, schedule, webhook, API/SDK, tool output; each sends a message to an agent | [triggers](https://relevanceai.com/docs/build/agents/build-your-agent/triggers.md) |
| Workforce | A graph of agents, tools and conditions; runs as a task of the same type | [workforces](https://relevanceai.com/docs/get-started/core-concepts/workforces.md), [SDK workforces](https://relevanceai.com/docs/sdk/workforces.md) |
| Job (legacy REST) | `/agents/trigger` returned `job_info` with `studio_id`, `job_id`, `conversation_id`; results were polled at `/studios/{studio_id}/async_poll/{job_id}` until an update such as `chain-success` | old page `relevanceai.com/docs/agent/api/conversation`, now 404; content from the search index snippet, not re-verified |

### API surface

| Call | Behaviour | Source |
|---|---|---|
| `POST /latest/agents/trigger` with `{message: {role, content}, agent_id, conversation_id?}` | Starts a task, or continues one when `conversation_id` is passed. Region-specific host | [API trigger](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/api-trigger.md), [API triggers for agents](https://relevanceai.com/docs/integrations/agent-integrations/build-your-own-triggers/api) |
| `POST /agents/{agent_id}/tasks/trigger` | Trigger an agent task (current public spec) | [jentic spec listing](https://jentic.com/apis/relevanceai.com/relevanceai.md) |
| `GET /agents/{agent_id}/tasks/{conversation_id}/view_steps` | Read a task's steps | same |
| SDK `agent.sendMessage(text, task?, files?)` | "creates a new task (the conversation thread) and returns it immediately"; passing a task continues it | [SDK agents](https://relevanceai.com/docs/sdk/agents.md) |
| SDK `agent.getTasks({filter: statuses, search, sort, page})` | Lists tasks, filterable by status | same |
| SDK `task.getMessages({after})`, `addEventListener("message" | "error" | "update")` | History and live updates; the SDK polls or opens a streaming connection "if one is available" | [SDK tasks](https://relevanceai.com/docs/sdk/tasks.md), [SDK streaming](https://relevanceai.com/docs/sdk/streaming.md) |
| MCP `relevance_trigger_agent` (sync, 120 s timeout), `relevance_trigger_agent_async` (returns `conversation_id`), `relevance_poll_agent_result` | Async trigger plus polling every 3 to 5 s until `complete` or `failed` | [MCP server](https://relevanceai.com/docs/integrations/mcp/mcp-server.md) |

The documented API trigger does not return the answer: "The agent's result must be sent to a destination you
configure, such as Google Sheets, a webhook, or another integration"
([API trigger](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/api-trigger.md)). The docs
also say the API is officially supported only for triggering agents and tools (same page, per search index).

### Task states

| SDK status | Meaning | Source |
|---|---|---|
| `not-started` | Created locally, not sent | [SDK tasks](https://relevanceai.com/docs/sdk/tasks.md) |
| `queued` | Waiting to start (capacity) | same |
| `running` | Agent processing | same |
| `idle` | Agent awaiting input; the normal resting state of a chat | same |
| `action` | Needs approval or was escalated; platform states `pending-approval` and `errored-pending-approval` map here | same, [SDK workforces](https://relevanceai.com/docs/sdk/workforces.md) |
| `paused` | Execution suspended | [SDK tasks](https://relevanceai.com/docs/sdk/tasks.md) |
| `completed`, `cancelled`, `error` | Terminal | same |
| Timed out | Listed in the product docs, not in the SDK enum | [task overview](https://relevanceai.com/docs/build/agents/give-your-agent-tasks/task-overview.md) |

`idle` is the important one: a chat task does not end after a reply. It rests in `idle` until the next message, and
it reaches `completed` only when the agent or a person completes it (inferred from the status list).

### Non-chat starts

| Start | How | Source |
|---|---|---|
| Integration events | 1,000+ integrations (Gmail, Slack, WhatsApp, Zapier); the trigger "sends a message to your Agent" | [triggers](https://relevanceai.com/docs/build/agents/build-your-agent/triggers.md) |
| Recurring schedule | Daily, weekly, monthly or a 6-field AWS EventBridge cron; "Max daily Scheduled Triggers" cap | [scheduled triggers](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/scheduled-triggers.md) |
| Agent schedules itself | Built-in Schedule Message tool: the agent sets a future message into its own task (follow-ups, reminders) | same |
| Webhook | Custom webhook trigger | [webhook triggers](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/custom-webhook.md) |
| Tool as trigger | A tool runs on a schedule and must return an array; a chosen output field is passed to the agent (one task per item is inferred) | [tools as triggers](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/tools-as-triggers.md) |
| Bulk schedule | Many tasks queued from a list; the Task Queue shows In Progress, Upcoming, Failed, Processed, Cancelled | [task queue](https://relevanceai.com/docs/build/agents/give-your-agent-tasks/task-queue.md) |

Trigger-to-agent settings decide whether each event is a new task or joins an existing one: "Always Start New Task"
or "Continue with One Task", plus variable mapping, context passing and a message format
([trigger to agent configuration](https://relevanceai.com/docs/build/workforces/workforce-features/trigger-to-agent-configuration.md)).
Every non-chat start is expressed as a message into a task. There is no separate "job" input shape.

### Human approval and escalation

| Setting | Behaviour | Source |
|---|---|---|
| Auto run | Tool runs when the agent chooses it | [approvals and escalations](https://relevanceai.com/docs/build/workforces/workforce-features/approvals-and-escalations.md) |
| Approval required | Agent drafts the call and waits; "The task will remain in a pending state until approved or rejected" | same |
| Let agent decide | Agent asks only when unsure | same |
| Max auto runs | Count of consecutive automatic uses before the task pauses for approval | [agent to tool configuration](https://relevanceai.com/docs/build/workforces/workforce-features/agent-to-tool-configuration.md), [subagents](https://relevanceai.com/docs/build/agents/build-your-agent/agent-settings/subagents.md) |
| Escalate to Manager | A tool added to the agent; routes to people or teams, tracked in Task View | [escalations](https://relevanceai.com/docs/agent/build-your-agent/escalations), [approvals and escalations](https://relevanceai.com/docs/build/workforces/workforce-features/approvals-and-escalations.md) |

Approval happens in the Task View UI ("approve, reject, or provide additional guidance"). The docs reviewed name no
API for approving, and the SDK messaging page does not mention approve or reject. Timeout actions for unanswered
approvals exist but are not described in detail (same page, FAQ).

### Limits, cancel, output, idempotency

| Topic | Finding | Source |
|---|---|---|
| Run time | Agent: 15 minutes "after each user action"; standard tool 15 min; 24-hour tools; bulk run 24 h | [system quotas](https://relevanceai.com/docs/admin/system-limits.md) |
| Concurrency | By plan; tasks queue at capacity | same |
| Step budget | Max auto runs per tool or subagent; no documented per-task step cap | [agent to tool configuration](https://relevanceai.com/docs/build/workforces/workforce-features/agent-to-tool-configuration.md) |
| Cancel | Bulk cancel from the queue; pause, complete, cancel per task in the task tab; no documented cancel endpoint | [task queue](https://relevanceai.com/docs/build/agents/give-your-agent-tasks/task-queue.md) |
| Structured output | Tools have typed outputs; no documented output schema for an agent task | [tool outputs](https://relevanceai.com/docs/build/tools/customize-tool/outputs.md) |
| Idempotency | Not documented | none found |
| Scoping | Organisation and project; project-level API keys override organisation keys; custom keys are visible to every builder in a project, so the docs advise separate projects for sensitive credentials | [org and project API keys](https://relevanceai.com/docs/enterprise/org-project-level-api-keys.md) |

### Workflows and agents

Relevance has three building blocks on one runtime: tools (deterministic step chains with typed inputs and outputs),
agents, and workforces. A workforce is a canvas of agents, tools and conditions; agents hand off by "AI connection"
(agent decides) or "Next step" (fixed transition)
([workforces](https://relevanceai.com/docs/get-started/core-concepts/workforces.md)). A workforce run is the same Task
type as an agent run, with a few listing differences
([SDK workforces](https://relevanceai.com/docs/sdk/workforces.md)). Subagents (an agent calling another agent) are
marked legacy in favour of workforces
([subagents](https://relevanceai.com/docs/build/agents/build-your-agent/agent-settings/subagents.md)). Tools are the
deterministic layer an agent calls; a tool can also start an agent as a trigger.

### What Ops AI takes from Relevance

| Finding | Consequence |
|---|---|
| One object for conversation and run, with `idle` as a resting state | Chat and background jobs share history, approvals and the console view; the cost is that a "run" has no clean end, and the per-turn result is not addressable |
| Every start is a message into a task, with a new-or-continue rule per trigger | One input shape for chat, schedule, webhook and API; the trigger config owns the routing |
| `action` status covers approval and escalation | The console needs one "waiting on a person" queue, across chat and background tasks |
| API trigger returns no result; callers poll or wire a destination | An agent run API is more useful when it returns a run id with a readable result and a final event |
| 15 minutes per user action | A turn has a hard wall-clock cap; long work happens across turns or in 24-hour tools |

## 2 OpenAI: Responses API, Conversations, Agents SDK, and the retired Assistants API

OpenAI has run both designs. The Assistants API had a thread with runs inside it; the Responses API has a response as
the unit of work, with a conversation as an optional container of items. The Assistants API "was officially
discontinued on August 26, 2026" ([migration guide](https://developers.openai.com/api/docs/assistants/migration)).

### Resources today

| Resource | What it is | Source |
|---|---|---|
| Prompt | Versioned configuration: model, tools, instructions (replaced Assistant) | [migration guide](https://developers.openai.com/api/docs/assistants/migration) |
| Response | One model run with input items and output items, including tool calls; the run primitive | same |
| Conversation | Durable container of items (messages, tool calls, tool outputs); "not subject to the 30-day TTL" | [conversation state](https://developers.openai.com/api/docs/guides/conversation-state) |
| Item | Generalised object: message, tool call, tool output, approval request (replaced run steps) | [migration guide](https://developers.openai.com/api/docs/assistants/migration) |
| `previous_response_id` | Chains one response to another without a conversation object; earlier input tokens are billed again | [conversation state](https://developers.openai.com/api/docs/guides/conversation-state) |

Chat is built on responses: "Multi-turn chat is constructed by repeatedly calling the Responses API with accumulated
message history, either manually chaining messages or using Conversations API"
([conversation state](https://developers.openai.com/api/docs/guides/conversation-state)). One chat turn equals one
response. The conversation holds history and nothing else; it has no status.

### Assistants to Responses mapping

| Before | After | Stated reason | Source |
|---|---|---|---|
| Assistants | Prompts | Configuration is easier to version and update | [migration guide](https://developers.openai.com/api/docs/assistants/migration) |
| Threads | Conversations | Streams of items beyond messages | same |
| Runs | Responses | Input and output items; explicit tool call loop | same |
| Run steps | Items | One generalised object for messages, tool calls, outputs | same |

Stated reasons for the change: responses use "a straightforward input-output model rather than asynchronous polling
cycles"; prompts own behaviour while application code owns orchestration; one configuration works across chat,
streaming and realtime sessions (same page). The Assistants run had nine states (`queued`, `in_progress`,
`requires_action`, `cancelling`, `cancelled`, `failed`, `completed`, `incomplete`, `expired`), and integrations were
told not to create a new run while a thread already had an active one
([runs reference](https://developers.openai.com/docs/api-reference/runs)). A run needing a client tool parked in
`requires_action` and expired if tool outputs were not submitted in time (expiry window from memory of the retired
docs, not re-verified). Inferred lesson: a thread that owns a run lock and a state machine forces every caller,
including simple chat, to poll a run.

### Background mode, streaming, resume, cancel

| Feature | Behaviour | Source |
|---|---|---|
| `background: true` | Response runs asynchronously "without having to worry about timeouts or other connectivity issues" | [background mode](https://developers.openai.com/api/docs/guides/background) |
| States | `queued`, `in_progress`, `completed`, `failed`, `cancelled`, `incomplete`; poll while queued or in progress | same |
| Cancel | POST cancel; "Cancelling twice is idempotent" and returns the final response | same |
| Stream and resume | `background` plus `stream`; every event has a `sequence_number`; reconnect with `starting_after` | same |
| Retention | Background data kept about 10 minutes for polling unless stored | same |
| Webhooks | `response.completed`, `.failed`, `.cancelled`, `.incomplete`; retries for 72 hours; `webhook-id` header is the dedup key | [webhooks](https://developers.openai.com/api/docs/guides/webhooks) |

Foreground and background are the same resource with one flag. A chat turn is a foreground response; a long job is a
background response; both can write into the same conversation (inferred from the shared `conversation` parameter).

### Human approval

| Layer | Mechanism | Source |
|---|---|---|
| Responses API, MCP tools | `require_approval` (`always`, `never`, or per tool). The response ends with an `mcp_approval_request` item. The caller creates a new response with `previous_response_id` and an `mcp_approval_response` item (`approval_request_id`, `approve`) | [MCP and connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp) |
| Agents SDK | `needs_approval` on a tool; `RunResult.interruptions` lists `ToolApprovalItem`s; `result.to_state()`, `state.approve()` or `state.reject()`, then `Runner.run(agent, state)`; `state.to_json()` stores a pending run in a database or queue | [Agents SDK human in the loop](https://openai.github.io/openai-agents-python/human_in_the_loop/) |

The SDK warns that a stored state must come from trusted storage, and servers must authenticate reviewers and check the
decision against a server-owned snapshot (same page). In both layers an approval ends the current run and a new run
resumes it. Nothing waits in memory.

### Agents SDK run loop and budgets

| Topic | Behaviour | Source |
|---|---|---|
| Loop | Call the model; final output of `output_type` with no tool calls ends the run; tool calls loop; handoffs switch agent | [running agents](https://openai.github.io/openai-agents-python/running_agents/) |
| Budget | `max_turns`, `MaxTurnsExceeded`; `ToolTimeoutError` | same |
| Output | `final_output` typed by the agent's `output_type` | same |
| History | Manual input list, SDK sessions, server `conversation_id`, or `previous_response_id`; sessions and server state cannot be mixed in one call | same |
| Durability | Delegated to Temporal, Dapr, Restate or DBOS | same |

### Workflows and agents

Agent Builder was OpenAI's visual workflow product: a workflow "is a combination of agents, tools, and control-flow
logic", published with an ID and versions, run through ChatKit or exported as Agents SDK code
([Agent Builder](https://developers.openai.com/api/docs/guides/agent-builder)). The same page says "OpenAI is
deprecating Agent Builder ... scheduled to shut down on November 30, 2026". The workflow there was a front end over the
same agent runtime and exported to plain SDK code; OpenAI kept the runtime and dropped the canvas.

### What Ops AI takes from OpenAI

| Finding | Consequence |
|---|---|
| Thread-owns-run with a run lock was replaced by stateless responses plus an item store | Keep the conversation a container with no status; put status on the run |
| One resource for foreground and background, with a flag | Chat turns and jobs should be the same run type |
| Events carry a sequence number and resume with `starting_after` | Ops AI already has `after=seq`; keep it as the contract |
| Approval ends a run; a new run carries the decision | Decide whether Ops AI resumes the same run (LangGraph interrupt) or starts a continuation; both are viable |
| Cancel is idempotent; webhooks dedup on an id | Cancel and webhook semantics to copy |

## 3 LangGraph Platform (LangSmith Deployment, Agent Server)

LangGraph's server is the most explicit run API of the set, and Ops AI already runs LangGraph graphs with a
checkpointer, so its shapes map almost one to one. Assistants contain threads, threads contain runs, and a durable
queue guarantees "at most 1 run can be executed for a given thread at one time"
([Agent Server](https://docs.langchain.com/langsmith/agent-server)).

### Resources

| Resource | What it is | Source |
|---|---|---|
| Assistant | A versioned configuration of a deployed graph ("agents configured for specific tasks") | [Agent Server](https://docs.langchain.com/langsmith/agent-server) |
| Thread | Conversation context; holds checkpointed state; has a status | same |
| Run | One execution of an assistant's graph, on a thread or stateless (no thread) | same, [streaming](https://docs.langchain.com/langsmith/streaming) |
| Cron | A schedule that creates runs, bound to a thread or stateless | [cron jobs](https://docs.langchain.com/langsmith/cron-jobs) |
| Store | Long-term memory across threads, Postgres by default | [Agent Server](https://docs.langchain.com/langsmith/agent-server) |

### States

| Object | States | Source |
|---|---|---|
| Run | `pending`, `running`, `error`, `success`, `timeout`, `interrupted` | [SDK schema.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/schema.py) |
| Thread | `idle`, `busy`, `interrupted`, `error` | same |

Status lives on both objects. The thread status tells a chat UI whether it can send; the run status tells a caller
how one execution ended. A human-in-the-loop pause shows as thread `interrupted` while the run that hit the interrupt
ends (inferred from the two enums and the resume-by-new-run pattern below).

### Endpoints and options

| Call | Behaviour | Source |
|---|---|---|
| `POST /threads/{thread_id}/runs` | Background run; returns `pending`; `client.runs.join()` waits for the end | [background run](https://docs.langchain.com/langsmith/background-run) |
| `POST /threads/{thread_id}/runs/stream`, `/runs/wait` | Same run, streamed or blocking (SDK `runs.stream`, `runs.wait`) | [streaming](https://docs.langchain.com/langsmith/streaming) |
| `runs.create(None, ...)` | Stateless run with no thread and no checkpoint storage | same, [SDK runs.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/_async/runs.py) |
| `GET /threads/{id}/runs/{run_id}/stream`, `join_stream` | Attach to a running background run | [streaming](https://docs.langchain.com/langsmith/streaming), [changelog](https://docs.langchain.com/langgraph-platform/langgraph-server-changelog) |
| `Last-Event-ID` / `last_event_id`, `stream_resumable` | Resume a dropped stream without missing events | [streaming](https://docs.langchain.com/langsmith/streaming) |
| `POST /threads/{id}/runs/crons`, `POST /runs/crons` | Thread cron (same thread every time) or stateless cron (new thread each time; `on_run_completed` `delete` or `keep`); UTC | [cron jobs](https://docs.langchain.com/langsmith/cron-jobs) |
| Cancel | `CancelAction` `interrupt` (stop) or `rollback` (stop and delete the run and its checkpoints); bulk cancel by status | [SDK schema.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/schema.py) |

Options on `runs.create`: `input` or `command`, `multitask_strategy`, `if_not_exists` (`create` or `reject` the thread),
`after_seconds` (delayed start), `webhook` (called on completion), `on_completion` (`delete` or `keep` a stateless
run's thread), `on_disconnect` (`cancel` or `continue`), `durability` (`sync`, `async`, `exit`), `interrupt_before` and
`interrupt_after`, `metadata`, `checkpoint_id` (run from an earlier checkpoint)
([SDK runs.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/_async/runs.py),
[SDK schema.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/schema.py)).

### Concurrency on one thread (double texting)

| Strategy | Behaviour | Source |
|---|---|---|
| `enqueue` (default) | New input waits for the current run | [double texting](https://docs.langchain.com/langsmith/double-texting) |
| `reject` | New run refused while one is in progress | same |
| `interrupt` | Current run stops, progress is kept, new input continues from there; the graph must handle half-finished tool calls | same |
| `rollback` | Current run stops and all its progress, including its input, is discarded | same |

### Human in the loop

A node calls `interrupt(payload)`. The server returns the interrupt with `resumable: true` and its namespace. The
caller starts a new run on the same thread with `Command(resume=value)`; the value becomes the return value of
`interrupt()` and execution continues from the checkpoint
([human in the loop](https://docs.langchain.com/langsmith/add-human-in-the-loop)). `interrupt_before` and
`interrupt_after` are static breakpoints, recommended for debugging (same page). There is no approval object: the
interrupt payload is free-form and the application decides who may resume.

### Scoping, idempotency, output, workflows

| Topic | Finding | Source |
|---|---|---|
| Multi-tenant | `@auth.authenticate` returns an identity; `@auth.on` handlers add filters such as `{"owner": identity}` to metadata on threads, assistants, runs and crons | [custom auth](https://docs.langchain.com/langsmith/custom-auth) |
| Idempotency | No request idempotency key; `if_not_exists` and `multitask_strategy` cover the thread-level cases | [SDK runs.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/_async/runs.py) |
| Output | The run's result is the final thread state (`join` returns state values) | [changelog](https://docs.langchain.com/langgraph-platform/langgraph-server-changelog) |
| Workflows | No separate product; an agent and a workflow are both graphs, deployed as assistants and run the same way | [Agent Server](https://docs.langchain.com/langsmith/agent-server) |

### What Ops AI takes from LangGraph

| Finding | Consequence |
|---|---|
| Thread and run each have a status | The console can show "thread waiting on approval" and "run 3 ended interrupted" without one status doing both jobs |
| One run endpoint with stream, wait and background as modes | Chat is a streamed run on a thread; a job is a background run, with or without a thread |
| Stateless runs and stateless crons | An agent job does not need a chat thread; the scheduler can create one per execution and delete it |
| Explicit multitask strategy | Ops AI's lease answers "one run per thread"; the strategy decides what a second message does, and should be a parameter |
| Resume is a new run carrying a command | Matches Ops AI's interrupt-based approvals; an approval decision becomes a run with `resume` input |
| `after_seconds`, `webhook` on the run | Put delayed start and completion callback on the run resource |

## 4 Letta

Letta treats an agent as a long-lived stateful service: "A stateful agent comprises of a system prompt, memory blocks,
messages (in-context and out-of-context), and tools" ([agents overview](https://docs.letta.com/guides/agents/overview)).
Messages go to the agent; each message creates a run; a run contains steps (same page).

### Resources

| Resource | What it is | Source |
|---|---|---|
| Agent | Prompt, memory blocks, tools, one message history by default | [agents overview](https://docs.letta.com/guides/agents/overview) |
| Conversation | "a message thread within an agent"; own context window, shared memory blocks and pooled searchable history; create, list, fork, delete | [conversations](https://docs.letta.com/guides/agents/conversations) |
| Run | One execution started by a message: `id`, `agent_id`, `status`, `stop_reason`, `background`, `callback_url`, timings | [create message async](https://docs.letta.com/api-reference/agents/messages/create-async) |
| Step | One model inference pass inside a run; `GET /v1/runs/{id}/steps` | [runs API listing](https://apis.apievangelist.com/store/letta-runs-api/) |
| Identity | A user attached to agents for multi-user setups | [agents overview](https://docs.letta.com/guides/agents/overview) |
| Sleep-time agent | A background agent sharing the primary agent's memory, rewriting it asynchronously | [sleep-time agents](https://docs.letta.com/guides/agents/sleep-time-agents) |

### Run API

| Call | Behaviour | Source |
|---|---|---|
| `POST /v1/agents/{agent_id}/messages` (and `/stream`) | Synchronous or streamed turn | [agents overview](https://docs.letta.com/guides/agents/overview) |
| `POST /v1/agents/{agent_id}/messages/async` | Returns a Run; fields `messages` or `input`, `max_steps`, `callback_url`, `client_tools`, `override_model`, `override_system` | [create message async](https://docs.letta.com/api-reference/agents/messages/create-async) |
| `GET /v1/runs`, `/v1/runs/{id}`, `/messages`, `/steps`, `/usage`, `/trace`; `POST /v1/runs/{id}/stream` | Read a run and re-attach to its stream | [runs API listing](https://apis.apievangelist.com/store/letta-runs-api/) |
| Background streaming | `run_id` plus `seq_id`; reconnect with `starting_after`; `/runs/active` finds live runs after a restart | [long-running](https://docs.letta.com/guides/agents/long-running) |

Run status: `created`, `running`, `completed`, `failed`, `cancelled`. Stop reason is separate: `end_turn`, `error`,
`max_steps`, `requires_approval` ([create message async](https://docs.letta.com/api-reference/agents/messages/create-async),
[human in the loop](https://docs.letta.com/guides/agents/human-in-the-loop)). Splitting "did it finish" (status) from "why
the loop stopped" (stop reason) keeps the state machine small.

### Human approval

Tools carry `requires_approval`. The run stops with `stop_reason: "requires_approval"` and an
`approval_request_message` with `tool_call_id`. The client sends a message of `type: "approval"` with
`approvals: [{approve, tool_call_id, reason}]`. In background mode the tool result arrives on the approval's own
stream, and the paused run "will not deliver the tool result"
([human in the loop](https://docs.letta.com/guides/agents/human-in-the-loop)). As with OpenAI, the decision is a new
input that starts a new run; the approval is a message type, so the same endpoint serves chat and approvals.

### Non-chat starts and concurrency

| Topic | Finding | Source |
|---|---|---|
| Schedules | One-time (`--at`) or recurring (`--cron`, UTC on cloud); by default "every scheduled run starts a new conversation", or targets the default, a given, or the agent's own conversation | [schedules](https://docs.letta.com/configuration/schedules/index.md) |
| Completion callback | `callback_url` on async runs, with `callback_sent_at` and `callback_status_code` recorded on the run | [create message async](https://docs.letta.com/api-reference/agents/messages/create-async) |
| Concurrency | "`agents.messages.create` is not thread-safe"; parallel work uses separate conversations | [conversations](https://docs.letta.com/guides/agents/conversations) |
| Budget | `max_steps` per run | [create message async](https://docs.letta.com/api-reference/agents/messages/create-async) |
| Workflows | None; multi-agent is agents messaging agents and shared memory blocks | [agents overview](https://docs.letta.com/guides/agents/overview) |

### What Ops AI takes from Letta

| Finding | Consequence |
|---|---|
| Run is created by any message, sync or async; the same run resource is read afterwards | One run table for chat turns and jobs |
| Status and stop reason are separate fields | `completed` with `stop_reason=requires_approval` reads cleanly; fewer states |
| Approval is an input message type | No separate approval endpoint is needed for the run API, though Ops AI's audit trail may still want one |
| Callback URL recorded on the run with its delivery status | Callers without a socket get the result; the run records whether delivery worked |
| Schedules choose new conversation or an existing one | Same rule Relevance exposes as "Always Start New Task" or "Continue with One Task" |

## 5 n8n

n8n is the reference for the "full deterministic" Ops AI edition. Everything is a workflow; an agent is a node inside
one. "An execution is a single run of a workflow" ([executions](https://docs.n8n.io/workflows/executions/)), and an
AI Agent node is a root node with a chat model, memory, tools and an optional output parser attached as sub-nodes
([AI Agent node](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/)).

### Resources

| Resource | What it is | Source |
|---|---|---|
| Workflow | Nodes joined by connections, started by a trigger node; versioned, published or unpublished, archivable | [public API workflow paths](https://github.com/n8n-io/n8n/tree/master/packages/cli/src/public-api/v1/handlers/workflows/spec/paths) |
| Execution | One run of a workflow; manual (editor) or production (trigger, schedule, polling) | [executions](https://docs.n8n.io/workflows/executions/) |
| Trigger node | Starts an execution: Webhook, Schedule, app events, Form, Chat Trigger, Execute Workflow Trigger (called by another workflow), Error Trigger, MCP Server Trigger | [nodes](https://docs.n8n.io/workflows/components/nodes/), [chat trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.chattrigger/), [MCP server trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/) |
| AI Agent node | Root node; sub-nodes for model, memory, tools, output parser | [AI Agent node](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/) |
| Credential | Stored connection secrets shared by nodes (inferred from node docs; not fetched here) | none fetched |

### Execution states and API

`ExecutionStatus` is `new`, `running`, `waiting`, `success`, `error`, `crashed`, `canceled`, `unknown`; recovery may
mark `new`, `running` or `unknown` as `crashed`, never `waiting`
([execution-status.ts](https://github.com/n8n-io/n8n/blob/master/packages/workflow/src/execution-status.ts)).

| Call | Behaviour | Source |
|---|---|---|
| `GET /executions?status=&workflowId=` | List executions, with data size limits and redaction controls | [getExecutions spec](https://github.com/n8n-io/n8n/blob/master/packages/cli/src/public-api/v1/handlers/executions/spec/paths/getExecutions.generated.yml) |
| `POST /executions/{id}/retry` | Starts a new execution linked by `retryOf`; `loadWorkflow` chooses the saved version or the version at the time | [retryExecution spec](https://github.com/n8n-io/n8n/blob/master/packages/cli/src/public-api/v1/handlers/executions/spec/paths/retryExecution.generated.yml) |
| `POST /executions/{id}/stop`, stop many | Cancel | [stopExecution spec](https://github.com/n8n-io/n8n/blob/master/packages/cli/src/public-api/v1/handlers/executions/spec/paths/stopExecution.generated.yml) |
| Start a workflow | No "run workflow" endpoint in the public API; external callers use a Webhook trigger (inferred from the path list) | [public API workflow paths](https://github.com/n8n-io/n8n/tree/master/packages/cli/src/public-api/v1/handlers/workflows/spec/paths) |

### How chat maps onto executions

"Every message to the Chat Trigger executes your workflow", so a 10-message conversation is 10 executions
([chat trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.chattrigger/)). The
conversation exists only as a memory sub-node keyed by session, shared by the Chat Trigger and the agent (same page).
Responses come from the last node, from Respond to Webhook or Chat nodes, or as a stream (same page). This is the
reverse of the agent-first platforms: chat is a trigger, and the execution is the run.

### Non-chat starts, waits and human steps

| Feature | Behaviour | Source |
|---|---|---|
| Schedule, webhook, app, form triggers | Each event starts a production execution | [executions](https://docs.n8n.io/workflows/executions/) |
| Wait node | Time interval, specific time, webhook call (unique `$execution.resumeUrl` per execution), form submitted; optional limit on wait time; waits over 65 s offload execution data to the database and reload on resume | [Wait node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/) |
| Send and Wait | Slack, Gmail and other nodes send a message with approve or approve-and-disapprove buttons; the workflow resumes when someone responds and records who responded and `respondedAt` | [Slack approvals](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.slack/approvals), [Gmail message operations](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.gmail/message-operations), [release notes](https://docs.n8n.io/changelog/release-notes) |
| Human review of AI tool calls | A tool with review enabled pauses the workflow and sends a request to Chat, Slack, Teams, Gmail, WhatsApp and others; approve runs the tool with the AI's input, deny cancels it and "the AI is informed of the rejection" | [human in the loop for AI tools](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/) |
| Error workflow | A separate workflow starting with Error Trigger, set per workflow; receives execution id, URL, error, stack, last node; Stop and Error forces it | [error handling](https://docs.n8n.io/flow-logic/error-handling/) |
| Node error policy | Retry On Fail; On Error: stop, continue, or continue through an error output | [nodes](https://docs.n8n.io/workflows/components/nodes/) |
| Concurrency | `N8N_CONCURRENCY_PRODUCTION_LIMIT` caps production executions; extra ones queue FIFO; queue mode uses workers and Redis | [concurrency control](https://docs.n8n.io/hosting/scaling/concurrency-control/) |

### Agents inside a deterministic product

| Relation | Mechanism | Source |
|---|---|---|
| Agent as a step | AI Agent node; Max Iterations (default 10), Require Specific Output Format with an output parser, Return Intermediate Steps, streaming | [tools agent options](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/tools-agent/) |
| Workflow as a tool | Call n8n Workflow Tool runs another workflow and returns its output; inputs fixed, mapped, or filled by the model with `$fromAI()`; an unpublished workflow returns "Workflow is not active and cannot be executed" | [Call n8n Workflow Tool](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolworkflow/) |
| Agent as a tool | AI Agent Tool node: a supervising agent calls sub-agents, each with its own prompt and tools, in the same execution | [VKTR report](https://www.vktr.com/ai-news/n8n-launches-ai-agent-tool-to-simplify-multi-agent-orchestration/) (secondary source) |
| Sub-workflow | Execute Sub-workflow with "wait for completion" on or off; parent and child executions link both ways | [Execute Sub-workflow](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executeworkflow/) |
| Workflows to outside agents | MCP Server Trigger exposes connected tools, including workflow tools, to MCP clients | [MCP server trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/) |

The agent in n8n has no identity outside the workflow that contains it: no agent resource, no agent run, and memory
lives in a sub-node. An n8n agent cannot be called from outside except by calling its workflow.

### What Ops AI takes from n8n

| Finding | Consequence |
|---|---|
| Execution states include `waiting` and `crashed`, and recovery never marks `waiting` as crashed | Ops AI's workflow run states should keep both; a paused run is healthy |
| Retry creates a new execution linked by `retryOf`, with a choice of workflow version | Matches Ops AI's "retry a step, run from a node" plan; keep the link field |
| Error workflow per workflow | A cheap, well-understood failure path for the deterministic product |
| Waits persist and resume by URL or form | Ops AI's review and timer ports already cover this; the resume URL is a pattern for external callers |
| Agent node with max iterations and output parser | The agent step needs a step budget and an output schema; Ops AI's `AgentPort.turn(request.output_schema)` already has the second |
| Chat as one execution per message | Works for a deterministic product, but leaves conversations without a run history of their own; the agentic edition should not copy it |

## 6 Other platforms (shorter)

### AWS Bedrock Agents and AgentCore Runtime

| Topic | Finding | Source |
|---|---|---|
| Run primitive | `InvokeAgent` on `/agents/{agentId}/agentAliases/{aliasId}/sessions/{sessionId}/text`; the same `sessionId` continues a conversation; `endSession` closes it; `memoryId` links long-term memory | [user confirmation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-userconfirmation.html), [InvokeAgent](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_InvokeAgent.html) |
| Session expiry | `idleSessionTTLInSeconds` set on the agent | [InvokeAgent](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_InvokeAgent.html) (via search summary) |
| Return of control | An action group with `RETURN_CONTROL` ends the invocation with `returnControl.invocationInputs` and an `invocationId`; the caller runs the action and sends `sessionState.returnControlInvocationResults` with the same `invocationId` in a new `InvokeAgent`; `inputText` is then ignored | [return of control](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-returncontrol.html) |
| User confirmation | Per action; result items carry `confirmationState` `CONFIRM` or `DENY`; framed as protection against prompt injection driving unintended actions | [user confirmation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-userconfirmation.html) |
| Multi-agent | A supervisor surfaces a collaborator's return of control with `agentId` and `collaboratorName`; the caller answers the supervisor | [return of control](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-returncontrol.html) |
| Long runs (AgentCore) | Same API for sync and async; agent reports `/ping` `Healthy` or `HealthyBusy`; idle sessions end after 15 minutes, busy ones live to the max lifetime; `add_async_task` and `complete_async_task` | [AgentCore long runs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) |

Bedrock has no run object at all: an invocation is a streamed request, and a pause is the end of that request with an
id to answer. AgentCore keeps a session process alive while it reports busy, which pushes job tracking into the
agent's own code.

### Google ADK and Vertex AI Agent Engine

| Topic | Finding | Source |
|---|---|---|
| Resources | Session ("a single conversation thread between a user and your agent") with id, app name, user id, events, state; Event (user message, agent response, tool action) | [ADK sessions](https://adk.dev/sessions/session/) |
| Scoping | `app_name`, `user_id`, `session_id` | same |
| Run | The Runner loads the session, runs the agent and appends each event with `append_event`; storage in memory, a database (row locking) or `VertexAiSessionService` | same |
| Pause | Long Running Function Tool returns an operation id and pauses the run; the client later sends a function response with the same call id | [function tools](https://adk.dev/tools-custom/function-tools/) |
| Agent as tool | `AgentTool` wraps an agent; runs in the parent's context, distinct from sub-agents | same |

ADK has no run resource either; the session's event log is the record, and a run is the act of appending events for
one input.

### Microsoft Copilot Studio

| Topic | Finding | Source |
|---|---|---|
| Event triggers | Let an agent "act autonomously in response to the defined event"; SharePoint, OneDrive, Planner, Dataverse, Recurrence | [event triggers](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-triggers-about) |
| Trigger to agent | The trigger sends "a JSON or plain text message ... to your agent as a message"; the payload can carry its own instructions per trigger | same |
| Identity | "event triggers can use only the agent author's credentials"; users of the agent may reach data through the author's authorisation; autonomous runs need every action on maker authentication | same |
| Billing | Each trigger payload counts as a message; a 10-minute recurrence sends a message every 10 minutes | same |
| Reliability guidance | Keep consecutive actions or topics under 15; otherwise move the sequence into a Power Automate flow called as an action | same |
| Workflows | Power Automate flows are separate products that an agent calls as an action | same |

Copilot Studio confirms the message-into-agent pattern for triggers and names the identity problem plainly: a
triggered run has no user, so it runs as someone, and the choice is a security decision.

## 7 Synthesis

### Comparison

| Platform | Run primitive | Chat built on runs? | Non-chat triggers | Human-in-loop resume | Workflows relation |
|---|---|---|---|---|---|
| Relevance AI | Task (conversation and run in one object), rests in `idle` | No: the task is the chat; each message re-activates it | Integrations, schedule (cron), webhook, API, tool output, bulk; each sends a message into a new or existing task | Same task waits in `action`; approved in Task View; no documented API | Workforce is a graph of agents, tools and conditions running as the same Task type |
| OpenAI Responses | Response (`background` flag for long runs) | Yes: one response per turn, history in a Conversation or `previous_response_id` | None built in; caller starts responses; webhooks on completion | Response ends with an approval item; a new response carries `mcp_approval_response` (Agents SDK: `RunState` approve, then run again) | Agent Builder canvas over the same runtime, being shut down 2026-11-30 |
| OpenAI Assistants (retired) | Run inside a thread, nine states | Yes, with a run lock on the thread | None | Run waits in `requires_action`; submit tool outputs | None |
| LangGraph Platform | Run on a thread or stateless; thread and run each have a status | Yes: a streamed run per message on a thread | Thread cron, stateless cron, `after_seconds`, API | Run ends at `interrupt()`; thread shows `interrupted`; a new run with `Command(resume=...)` continues | Same runtime: agents and workflows are both graphs |
| Letta | Run created by any message (sync, stream or async) | Yes: run per message on an agent or conversation | Schedules (one-time or cron) into a new or chosen conversation; `callback_url` | Run stops with `stop_reason=requires_approval`; an `approval` message starts the continuation | None; agents message agents |
| n8n | Execution of a workflow | Inverted: chat is a trigger; each message is one execution | Trigger nodes: schedule, webhook, app, form, chat, MCP, sub-workflow, error | Same execution waits in `waiting` (Wait node, send-and-wait, tool review), resumes by URL or response | The product is the workflow; the agent is a node and a sub-agent tool |
| AWS Bedrock Agents | `InvokeAgent` call on a session; no run object | Session plus invocations | None in the agent API (AgentCore keeps a busy session alive) | Invocation ends with `returnControl`; next `InvokeAgent` sends results with the same `invocationId` and `confirmationState` | Separate (Step Functions, not covered) |
| Google ADK | Runner appends events to a session; no run object | Session of events | None in ADK | Long-running tool pauses; client sends a function response with the same call id | `AgentTool` and sub-agents; workflow agents not covered here |
| Copilot Studio | Message into the agent | Yes for chat; triggers send messages too | Event triggers including Recurrence, run as the agent author | Not covered | Power Automate flows, called as actions |

### What most platforms share

| Pattern | Seen in |
|---|---|
| Every non-chat start is a message into an agent, with the trigger's payload as content and sometimes its own instructions | Relevance triggers, Copilot Studio event triggers, Letta schedules, LangGraph thread cron |
| The trigger decides whether an event starts a new thread or continues one | Relevance "Always Start New Task" or "Continue with One Task"; Letta `--conversation`; LangGraph thread cron versus stateless cron |
| One run resource for foreground and background, with a mode or flag | OpenAI `background`; LangGraph `stream`, `wait`, background; Letta `/messages`, `/stream`, `/async`; AgentCore one API for sync and async |
| Stream events carry a sequence cursor and a dropped client resumes from it | OpenAI `sequence_number` and `starting_after`; Letta `seq_id`; LangGraph `Last-Event-ID`; Ops AI `after=seq` |
| Approval is a per-tool policy | Relevance auto, required, agent decides, max auto runs; OpenAI `require_approval`; Agents SDK `needs_approval`; Letta `requires_approval`; Bedrock per-action confirmation; n8n per-tool review |
| One active run per thread, with a rule for the second message | LangGraph queue and multitask strategies; Assistants run lock; Letta advises separate conversations for parallel work |
| A step budget per run | Agents SDK `max_turns`; Letta `max_steps`; n8n Max Iterations (10); Relevance max auto runs and 15 minutes per user action |
| A completion callback recorded on the run | LangGraph `webhook`; Letta `callback_url` with delivery status; OpenAI webhooks with a dedup id |

### Where they disagree

| Question | Camp | Platforms |
|---|---|---|
| Who owns the pause for a human decision | The same run stays alive in a waiting state and resumes | n8n `waiting`, Relevance `action`, AgentCore `HealthyBusy` |
| | The run ends at the pause; the decision is input to a new run on the same thread | OpenAI approval items, Agents SDK `RunState`, LangGraph `Command(resume)`, Letta approval messages, Bedrock return of control, ADK long-running tool responses |
| Is conversation the same object as run | Yes | Relevance (task), n8n inverted (execution per message, no conversation object) |
| | No: conversation is a container, run is the unit of work | OpenAI, LangGraph, Letta |
| Where status lives | Run only | OpenAI, Letta |
| | Thread and run | LangGraph |
| | Task only | Relevance |
| Is the workflow product separate from the agent runtime | Same runtime | LangGraph, Relevance workforces, OpenAI Agent Builder (exported to SDK code) |
| | Separate product the agent calls | Copilot Studio with Power Automate, n8n (agent lives inside the workflow) |

The pause question is the one that changes Ops AI's design. The second camp is larger and matches what Ops AI already
does: a LangGraph interrupt checkpoints the thread, and the decision resumes it with `Command(resume)`
([human in the loop](https://docs.langchain.com/langsmith/add-human-in-the-loop)). Ending the run at the pause means no
worker or lease is held while a person decides, the decision is an auditable input, and a resume is an ordinary run
that can be queued, retried and cancelled. The first camp's advantage, one run id from start to finish, can be kept at
the read layer by linking runs (`resumes_run_id`), the way n8n links retries with `retryOf`
([retryExecution spec](https://github.com/n8n-io/n8n/blob/master/packages/cli/src/public-api/v1/handlers/executions/spec/paths/retryExecution.generated.yml)).

### Recommended run API for Ops AI

Resources:

| Resource | Fields that matter | Backed by |
|---|---|---|
| Agent | Versioned config (instruction, model alias, tools with approval policy, knowledge, skills, guardrails, budget, optional output schema) | OpenAI prompts replacing assistants; Relevance agents |
| Thread | Agent id, team, owner, status (`idle`, `busy`, `waiting`, `error`), `origin` (chat, trigger id, schedule id, workflow run), metadata; no run logic | LangGraph thread status; OpenAI Conversation as container |
| Run | `id`, `agent_id`, `agent_version`, `thread_id` (nullable for stateless), `input` (messages) or `resume` (decision for a named interrupt), `mode` (`stream`, `wait`, `background`), `status`, `stop_reason`, `output` (validated against `output_schema` when given), `budget` (max model calls, tool calls, wall time), `usage`, `requested_by` (person, trigger, schedule, workflow node, agent), `idempotency_key`, `resumes_run_id`, `parent` (workflow run and node, or parent thread and tool call), `webhook` with delivery status, `start_after` | LangGraph run options; Letta Run fields; OpenAI background |
| Run event | `seq`, run id, thread id, type, data; the stream and the record are the same rows | Ops AI `thread_events`; OpenAI `sequence_number`; Letta `seq_id` |
| Approval | One row per interrupt: call, args, policy, decided by, decision, step-up; the decision is then sent as a run `resume` | Ops AI approvals and Reviews; Agents SDK advice to check decisions against a server-owned snapshot |
| Schedule and trigger bindings | Source, agent, payload mapping, `thread_policy` (`new` or `continue:<key>`), identity to run as, daily cap | Relevance trigger settings and daily cap; Letta `--conversation`; LangGraph crons; Copilot identity warning |

Run status: `queued`, `running`, `completed`, `failed`, `cancelled`. Stop reason on `completed`: `end_turn`,
`requires_approval`, `budget_exhausted`, `guardrail`, `output_invalid`. Thread status is derived: `busy` while a run is
active, `waiting` while an approval is open, otherwise `idle` or `error`. This follows Letta's split of status and stop
reason ([create message async](https://docs.letta.com/api-reference/agents/messages/create-async)) and LangGraph's
separate thread status ([SDK schema.py](https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/schema.py)).

Endpoints in plain terms:

| Endpoint | Does |
|---|---|
| `POST /v1/agents/{id}/runs` | Start a run. With `thread_id` it continues that thread; without, it is stateless (or creates a thread when `thread: {create: true}`). `mode=stream` returns SSE, `wait` returns the finished run, `background` returns 202 with the run. `Idempotency-Key` header returns the existing run on repeat. `multitask` (`reject`, `enqueue`, `interrupt`) decides what happens when the thread is busy |
| `GET /v1/runs/{id}`, `GET /v1/runs?agent=&thread=&status=&requested_by=` | Read and list runs |
| `GET /v1/runs/{id}/events?after=seq` | Attach or re-attach to a run's stream |
| `POST /v1/runs/{id}/cancel` | Cancel; idempotent, returns the final run |
| `POST /v1/approvals/{id}/decision` | Record the decision (with step-up) and start the resume run; returns the new run |
| `GET /v1/threads/{id}`, `/messages`, `/runs` | Thread view for chat and for background threads alike |
| `POST /v1/agents/{id}/schedules`, `/triggers` | Bindings that start runs by the rules above |

Event types: `run.started`, `message.delta`, `message.completed`, `tool.call`, `tool.result` (with widget part),
`approval.requested`, `run.completed` (with stop reason and output), `run.failed`, `run.cancelled`. Webhooks send the
last three, keyed by an event id for deduplication, as OpenAI does
([webhooks](https://developers.openai.com/api/docs/guides/webhooks)).

Layers on top:

| Layer | Built as |
|---|---|
| Chat | A thread with `origin=chat`; each message is `POST /runs` with `thread_id`, `mode=stream`, `multitask=enqueue` or `reject`. The chat UI reads thread status to enable the box and runs to draw "waiting on approval" |
| Agent job | `POST /runs` with `mode=background`, an `output_schema`, a budget, and either no thread or a thread created per execution; schedules and triggers call the same endpoint. Results arrive by webhook, by event, or by `GET /runs/{id}` |
| Workflow agent step | `AgentPort.turn` becomes `POST /runs` with `mode=wait` (inside the worker), `idempotency_key` derived from run, node and iteration, `output_schema` from the node, `requested_by` the workflow node, and a stateless or per-case thread. An approval inside it opens the same approval row, and the workflow node waits on the resume run's end |
| Workflow as an agent tool | Unchanged from [workflows as tools](../../architecture/workflows-as-tools.md): a child workflow run keyed by the tool call; the agent run that called it records the child as `parent` |

### What to avoid

| Avoid | Platform that hit it | Source |
|---|---|---|
| A thread that owns a run lock and a nine-state run machine, polled by every chat turn | OpenAI Assistants, discontinued 2026-08-26 and replaced by stateless responses plus a conversation container | [migration guide](https://developers.openai.com/api/docs/assistants/migration) |
| An API trigger that returns no result, leaving callers to wire a destination or poll a separate job endpoint | Relevance API trigger | [API trigger](https://relevanceai.com/docs/build/agents/build-your-agent/agent-triggers/api-trigger.md) |
| An agent with no identity outside its workflow, so it cannot be called, listed or audited as an agent | n8n AI Agent node | [AI Agent node](https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/) |
| Triggered runs on the author's credentials, letting any user reach data through them | Copilot Studio event triggers | [event triggers](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-triggers-about) |
| A busy-ping that keeps a process alive as the job tracker | AgentCore Runtime (15-minute idle termination when the ping thread blocks) | [AgentCore long runs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) |
| Concurrent messages to one agent history with no queue | Letta: "`agents.messages.create` is not thread-safe" | [conversations](https://docs.letta.com/guides/agents/conversations) |
| A visual workflow builder that duplicates the agent runtime | OpenAI Agent Builder, shutting down 2026-11-30 | [Agent Builder](https://developers.openai.com/api/docs/guides/agent-builder) |

## 8 Two products, one platform

Ops AI is designed to ship as a "full agentic" edition in the manner of Relevance AI and a "full deterministic"
edition in the manner of n8n or LangGraph. Built side by side, they own different things and share a substrate.

| Owned by the agentic edition | Owned by the deterministic edition |
|---|---|
| Agents and their versions; threads; agent runs; chat; memory and knowledge use; the "waiting on a person" task view for agent work | Workflows and their versions; workflow runs and steps; node types and ports; waits and timers; error paths and retry; replay and pins |
| Relevance equivalent: agents, tasks, Task View, workforces | n8n equivalent: workflows, executions, node settings, error workflows |

| Shared substrate | Why it is shared | Ops AI today |
|---|---|---|
| Tool registry, gateway and credentials | Both call the same operations under the same policies; Relevance tools and n8n credentials both sit under agents and workflows alike | tools-service `POST /v1/calls` |
| Approvals and reviews | One queue of "waiting on a person" across both, with one decide path and step-up | Reviews, Cases, approvals route |
| Trigger sources | An email, webhook or schedule emits one event; a binding routes it to an agent run or a workflow run | Workflow triggers today; agent triggers not built |
| Run history and events | One event table and one `after=seq` stream contract, so the console's activity view reads both | `thread_events`, `EventPort` |
| Tenancy, identity and `requested_by` | Every run records who or what started it and runs under a team-scoped identity | Leases, tenant-scoped saver |
| Budgets and metering | Model and tool call ledgers apply to both | model ledger, metering |

| Crossing | Mechanism | Prior art |
|---|---|---|
| Agentic to deterministic | A published workflow is a tool an agent may call; the child workflow run links to the calling agent run | Relevance tools; n8n Call n8n Workflow Tool; Ops AI `workflow__<id>` |
| Deterministic to agentic | An agent step calls the agent run API in `wait` mode with an output schema | n8n AI Agent node; Ops AI agent node via `AgentPort` |
| Agentic to agentic | An agent called as a tool is a child agent run | n8n AI Agent Tool; ADK `AgentTool`; Relevance workforce handoffs |

With both crossings going through the two run APIs (agent runs and workflow runs), either edition can ship without
the other: the agentic edition hides the workflow builder and keeps workflows-as-tools optional; the deterministic
edition keeps the agent node and hides chat. The substrate rows above are the parts to build once.

### Coverage gaps

Multi-tenant scoping was documented for LangGraph (custom auth filters), Letta (identities), ADK (`app_name`,
`user_id`, `session_id`) and Relevance (organisation and project keys). The pages fetched for OpenAI, n8n, Bedrock and
Copilot Studio did not cover it beyond Copilot's author-credentials rule. Salesforce Agentforce, Sierra, Decagon, Dust
and CrewAI were not researched.
