# A write held in a chat is listed in Reviews and approved there

Status: current. Id: `uc-057`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Maya Okafor (approver), Nadia Petrov (Security), Priya Shah (admin) |
| The scripted model | the ui harness's agents-service; a message `call <tool> <json>` makes the model call it |
| The fake bank on https | the ui harness's `tools: { bank: true }` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James publishes a module with one write and grants it to a new agent | 200 |
| 2 | He asks the agent in chat to call the write | the call is held on an approval card |
| 3 | `GET /reviews` as Maya | the hold, with `origin.kind` chat and the chat thread's id |
| 4 | Maya opens Reviews | the row reads "From chat" and "Chat with <agent>"; its detail links to the conversation |
| 5 | She approves it there | `POST /reviews/{id}/decision` 200; the write runs once at the gateway |

The chat card and the Reviews row decide the same review through the same decide call
(docs/architecture/tool-lifecycle.md).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-057-ui.mjs` | passing |

## Non-vacuous check

Step 3 fails on agents-service before c-048 T013, whose review list skipped chat-agent threads.
