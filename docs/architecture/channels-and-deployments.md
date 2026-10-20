# Channels and deployments

Status: current, updated 2026-10-11 against HEAD; every decision is an option until the maintainers confirms it.

## A deployment is one row

A deployment puts one graph pointer on one channel with that channel's settings. Deploying the same graph on a second
channel adds a row and changes nothing in the graph. An agent deploys the same way, as its one-node wrapper graph.

| Field | Designed | In code (`deployments`, migration 0010) |
|---|---|---|
| Graph | A pointer: `wf_d@production` or `ag_x@production` | A graph name; threads take the latest version |
| Channel | `chat`, `mailbox`, `api`, `mcp`, `schedule`, `webhook` | Free text; `mailbox` is the one adapter built |
| Environment | `test` or `production` | Not stored |
| Settings | Mailbox address, allowed sender domains, API key, schedule, multitask default | `multitask` (default `enqueue`) and `paused` |
| Budget | Default caps (`maxCalls`, `maxTokens`, `maxCost`) for every thread the deployment opens | In code (migration 0013): applied when `POST /v1/threads` creates a thread with this `deploymentId` and no `budget` of its own; a spent budget pauses the thread ([human-in-the-loop.md](human-in-the-loop.md)) |
| Paused | Stops new threads; open threads finish and replies still deliver | In code |

## The adapter contract

Every channel adapter turns what arrives into the same two calls: find or create the thread by its external key,
then run the graph with the input. Each adapter keeps five guarantees:

| # | Guarantee | Mailbox adapter today |
|---|---|---|
| 1 | Authenticate the sender | Designed: DKIM, DMARC and allowed domains; not checked on the fake source |
| 2 | Map the sender to a principal; the run's token carries `sub` and `act` | Designed ([identity-and-tenancy.md](identity-and-tenancy.md)) |
| 3 | Dedupe by external key: `POST /v1/threads` returns the existing thread | In code: unique `external_key`, find-or-create in one transaction |
| 4 | Deliver pause notices through an outbox written in the same transaction as the event | Designed |
| 5 | Refuse new threads while the deployment or agent is paused | In code: 409 `deployment_paused` for a new key, existing thread returned for a known one |

Two further rules: every adapter reads and writes the one thread event schema ([api.md](api.md)), and MCP returns
only a review id, so case content stays inside the console.

## Identity and keys per channel

| Channel | Authenticated caller | `sub` | `act` | External key |
|---|---|---|---|---|
| Chat | Signed-in user (SSO) | The user | The graph version (`ag_x@7`) | Client conversation id |
| Mailbox | Sender by DKIM, DMARC, allowed domains | The mailbox's process principal | The graph version | `deployment id:Message-ID` |
| API | Client credential | The client's principal, or the end user when a user token is passed | The graph version | Caller's key, or one per request |
| MCP | The assistant's user, by MCP OAuth | The user | The assistant client, then the graph version | Assistant session id |
| Schedule | The timers poller | The schedule's process principal | The graph version | `deployment id:tick time` |
| Event, webhook | Sender by signature | The deployment's process principal | The graph version | `deployment id:event id` |

The external key includes the deployment id, so one message sent to two deployments opens one case in each.

## A second input on a busy thread

A thread runs one run at a time. The `multitask` setting decides what happens to input that arrives while a run holds
the thread: `reject`, `enqueue` (default) or `interrupt`.

| Path | Behaviour today |
|---|---|
| `POST /v1/threads/{id}/runs/stream` | Rejects with 409 `run_active`, naming the maintainers and the run |
| Channel input (`POST /v1/threads/{id}/inbox`) | Enqueues in `thread_inbox`, unique on `(thread, message key)`; drained in order by `execute` after the lease is released |
| Reply to a waiting case | Delivered at once; restarts the SLA timers |
| Reply to a finished case | Opens a follow-up thread linked by `parent_thread_id` |
| Timer due during a run | Rejected and retried next poll; cancelled if the run decided the step |

## Mailbox adapter

Built in E6 against a fake Microsoft Graph source
([mailbox-adapter](../services/agents-service/experiments/mailbox-adapter.md)); a real tenant run is next. The
adapter calls the thread API over HTTP, so no graph knows that mail exists: a graph receives an `email` whose
attachments are file references in `channel_files`.

| Fact | Handling |
|---|---|
| Message-IDs vary in brackets and case | Strip brackets, lower-case the domain, keep the local part's case (RFC 5322) |
| A message with no Message-ID | Key `synthetic:` + SHA-256 of sender, received time and subject; two messages identical on all three merge |
| Graph sends `@removed` for deletes and folder moves | No-op; a message moved back returns as a duplicate |
| A delta request fails mid-poll | The cursor is saved only after the last page, so the poll repeats from the previous cursor with no duplicate case |
| Repeatable after a crash | Run id derived from the external key, inbox unique per message, attachment ids derived from the message, ledger (`channel_messages`) written after handling |
| Pause | Holds new cases only; replies to existing cases still deliver. Holding replies too needs a second flag |
| Open race | A lease can be taken between the inbox state check and the insert, so a reply can reach a newly started run out of order with queued replies. Fix: check and insert under the lease row lock |
| Cost | 22 SQL statements per first-poll message (starting the run dominates); 1.1 per replayed duplicate; 83 messages/s and 2,683 replays/s on SQLite with a fake model |
| Large attachments | Graph's inline `contentBytes` is size-limited; the real source must fetch large attachments separately |

## Channels still to build

| Channel | Needs |
|---|---|
| Mailbox on a real tenant | `GraphMailSource` against a test tenant, sender authentication, PostgreSQL numbers |
| API | Client credentials, webhooks for `waiting_review` and `finished` |
| MCP | MCP OAuth, a review-id-only result for a pause |
| Schedule | Ticks fired by the timer poller, keyed by deployment and tick time |
| Console chat on the thread calls | `/chat/*` moved onto `agent_wrapper` threads ([api.md](api.md)) |
