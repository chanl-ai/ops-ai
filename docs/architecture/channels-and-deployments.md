# Channels and deployments

Status: current, checked against the code on 2026-11-18. Built: deployments on the widget, API and MCP channels, the Email received trigger, and input queued for a busy thread. Designed and not built: schedule and webhook channels, deployment environments, sender authentication for mail.

A channel is a way work reaches an agent or a workflow: a chat widget on a bank's website, an API key, an outside
assistant over MCP, or a team mailbox. A deployment puts one agent or workflow on one channel with that channel's
settings, and a mailbox starts a workflow through its trigger. Whatever the channel, the work arrives as the same
thread and run calls, so no agent or workflow knows which channel it came from.

The console's Channels list, which shows every channel under the record that holds it with its health and traffic, is
described on the [agents service](../services/agents-service/overview.md#channels) page.

## A deployment is one row

Deploying the same graph on a second channel adds a row and changes nothing in the graph. An agent deploys the same
way, as its one-node wrapper graph. A deployment belongs to the team that made it; creating or changing one needs a
builder or admin of that team (`services/agents-service/src/ops_agents/api/routers/channels.py:34-39`).

| Field | Designed | In code (`deployments`, `routers/channels.py:46-53`) |
|---|---|---|
| Graph | A pointer: `wf_d@production` or `ag_x@production` | A graph name; threads take the latest version |
| Channel | `widget`, `api`, `mcp`, `schedule`, `webhook` | `widget`, `api` or `mcp`. Mail starts workflows through the Email received trigger instead (below) |
| Environment | `test` or `production` | Not stored |
| Multitask | What a second input does while a run holds the thread | `enqueue` (default) or `reject` |
| Budget | Default caps (`maxCalls`, `maxTokens`, `maxCost`) for every thread the deployment opens | In code: applied when `POST /v1/threads` creates a thread with this `deploymentId` and no budget of its own; a spent budget pauses the thread ([human-in-the-loop.md](human-in-the-loop.md)) |
| Paused | Stops new threads; open threads finish and replies still deliver | In code: 409 `deployment_paused` for a new key, the existing thread returned for a known one |

## The channels built today

| Channel | Who calls | What starts | Where |
|---|---|---|---|
| Chat widget | A visitor on an allowed website, in a session the bank's server mints with the deployment's mint key | A thread on the deployment's agent, pinned at a version or Latest | Widget deployments (`wd_…`) in agents-service; mint keys stored as a SHA-256 of the secret (`services/agents-service/src/ops_agents/store/widget_keys.py`) |
| API | A caller holding a platform API key; a key scoped to one agent or workflow starts only that target, else 403 `key_target` | A thread or a live run | [platform service](../services/platform-service/overview.md) issues the keys; agents-service checks the target (`auth.require_key_reaches`) |
| MCP | An outside assistant with an API key or a person's token on the team's address `/mcp/{team}` | One gateway call per `tools/call`, as a test run; a write is refused | [tools service](../services/tools-service/overview.md), `services/tools-service/src/ops_tools/mcp_server.py` |
| Email | The worker, reading a team mailbox (Gmail, IMAP or Microsoft 365) through tools-service, so the password never reaches agents-service | One run of the live workflow whose Email received trigger names the mailbox, per matching message, recorded as started by `trigger:email:<mailbox>` | `services/agents-service/src/ops_agents/api/email_trigger.py`; mailboxes are connected on Channels › Email |

Binding a mailbox to a workflow is decided when the workflow version goes live, since going live takes a publish
request; only a workflow the mailbox's team owns can bind it, and the listener checks that rule again before each read.
A paused mailbox is not read. When a mailbox refuses the stored read position, the trigger starts again from now and
records a `cursor_reset` row, so mail between the last read and the reset is not read
([agents service, Activity](../services/agents-service/overview.md#activity)).

## The adapter contract

Every channel turns what arrives into the same two calls: find or create the thread by its external key, then run the
graph with the input.

| # | Guarantee | State |
|---|---|---|
| 1 | Authenticate the sender | In code for widget sessions, API keys and MCP callers. Designed for mail: DKIM, DMARC and allowed sender domains are not checked |
| 2 | Map the caller to a principal; the run's token carries `sub` and `act` | Partial: the caller is the principal; `act` as the graph version is designed ([identity-and-tenancy.md](identity-and-tenancy.md)) |
| 3 | Dedupe by external key: `POST /v1/threads` returns the existing thread | In code: unique `external_key`, find-or-create in one transaction |
| 4 | Deliver pause notices through an outbox written in the same transaction as the event | Designed |
| 5 | Refuse new threads while the deployment or agent is paused | In code |

Two further rules: every channel reads and writes the one thread event schema ([api.md](api.md)), and MCP returns only
a review id for a pause, so case content stays inside the console.

## Identity and keys per channel (designed)

| Channel | Authenticated caller | `sub` | `act` | External key |
|---|---|---|---|---|
| Chat | Signed-in person, or a widget session | The person | The graph version (`ag_x@7`) | Client conversation id |
| Email | The mailbox the trigger reads | The mailbox's process principal | The graph version | Mailbox and message id |
| API | API key | The key's principal, or the end user when a user token is passed | The graph version | Caller's key, or one per request |
| MCP | The assistant's user | The user | The assistant client, then the graph version | Assistant session id |
| Schedule | The timers poller | The schedule's process principal | The graph version | `deployment id:tick time` |
| Event, webhook | Sender by signature | The deployment's process principal | The graph version | `deployment id:event id` |

The external key includes the deployment id, so one message sent to two deployments opens one case in each.

## A second input on a busy thread

A thread runs one run at a time. The deployment's `multitask` setting decides what happens to input that arrives while
a run holds the thread.

| Path | Behaviour today |
|---|---|
| `POST /v1/threads/{id}/runs/stream` | Rejects with 409 `run_active`, naming the owner and the run |
| Channel input (`POST /v1/threads/{id}/inbox`) | Enqueues in `thread_inbox`, unique on `(thread, message key)`, drained in order after the lease is released; with `multitask: reject` it is refused while a run holds the thread. The thread's row lock is held until commit, so no run can take the lease between the check and the write (`services/agents-service/src/ops_agents/api/channels/inbox.py:28-40`) |
| Reply to a waiting case | Delivered at once; restarts the SLA timers |
| Reply to a finished case | Refused with 409 `thread_closed`; the channel opens a new case. No request links one case to another: `parent_thread_id` is set only where the server opens a child |
| Timer due during a run | Rejected and retried next poll; cancelled if the run decided the step |

## Not built yet

| Channel or part | Needs |
|---|---|
| Schedule deployments | Ticks fired by the timer poller, keyed by deployment and tick time; workflows already start on a schedule trigger |
| Webhooks | Signed events in, and webhooks out for `waiting_review` and `finished` |
| Sender authentication for mail | DKIM, DMARC and allowed sender domains |
| Deployment environments and pointers | A deployment names a graph, not `@production` |
| Console chat through the SDK's thread calls | The console's chat routes are a facade over `agent_wrapper` threads ([api.md](api.md)) |
