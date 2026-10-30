# The console works cases

Status: current. Id: `uc-139`. Service: `console` and `agents-service`. Layers: ui.

The Cases page listed workflow runs, with no customer, owner or deadline. It now lists the team's cases from
`/v1/cases` with both deadlines, filters on the server, opens each case on its timeline, and the run list moved
to Workflows › Runs.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, platform-service and console (ISOLATED=1 adds 1000) |

James works Operations' cases. The script opens three for Alex Martin: one due, one past both deadlines, one waiting on
the customer.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Cases | Each case shows its customer; the due one says the time left, the late one says overdue on both deadlines, the waiting one says paused; no runs are listed |
| 2 | He opens the Overdue view | The request asks the server for overdue cases; only the late one shows |
| 3 | He opens the late case, sets its priority to High and adds a note | Both land on the timeline, on the page and the server |
| 4 | He opens an old `/cases?run=` link | It lands on Workflows › Runs with the same run |
| 5 | Start a workflow's run through the API, then open Workflows › Runs | One list, with no engine tabs, shows it with the server's status, and the row opens the run |
| 6 | He opens the Overview | Needs a person and Waiting on review equal what GET /v1/overview counts |
| 7 | He searches Cases for “Disputed wire” | The console asks the server, and only that case is listed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-139-ui.mjs` | passing |
