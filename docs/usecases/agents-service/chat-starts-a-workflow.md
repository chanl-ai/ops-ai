# Chat starts a workflow

Status: current. Id: `uc-020`. Service: `agents-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790 (ISOLATED=1 adds 1000) |

The script starts the agents service on the scripted model. `ag_dispute` holds the grant `workflow:dispute_email`,
and the registry seeds `dispute_email` published.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Pause `dispute_email`, ask `ag_dispute` in chat to start it | No tool call and no child thread: a paused workflow is not offered |
| 2 | Set it live again and ask again | The agent calls `workflow__dispute_email`; the reply says the child is waiting for a review and names it |
| 3 | Cases, Needs a person | The child is a row, started by the agent |
| 4 | Decide the child's review | 200; the conversation then shows the child's outcome |

In the console (ui layer), with chat, Cases and Reviews pointed at the scripted agents service:

| # | Step | Expected |
|---|---|---|
| 1 | `/chat?agent=ag_dispute`, "Start workflow dispute_email: …" | A `workflow__dispute_email` tool card; the reply "The workflow is waiting for a review: gth_…" |
| 2 | `/cases` | The child's row, "Started by agent Card Dispute Resolver", waiting on a person |
| 3 | `/reviews`, the child, Approve | One decision, 200, no step-up (a write) |
| 4 | Back to the conversation | "The dispute email workflow (gth_…) finished" |
| 5 | Pause `dispute_email`, ask again in a new conversation | "I could not find that.", no tool card, no new child in Cases |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-020-api.py` | passing |
| ui | `agents-service/scripts/test-uc-020-ui.mjs` | passing |

## Non-vacuous check

`a paused workflow is not called` with `and no child thread starts`, against `the agent calls the workflow as a tool`
for the same request once it is live: the only difference is the registry status. The ui script runs the paused half
last and checks it the same way, by the reply, the missing tool card and an unchanged count of agent-started runs.
