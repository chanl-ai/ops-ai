# A case page says what it is about, what it waits on and what is next

Status: current. Id: `uc-256`. Service: `console`. Layers: ui. Card: an earlier change.

A case is opened by a workflow and then waits on people. Its page reads one assembled call (`GET /v1/cases/{id}`,
an earlier change) and shows the case's header and next action, its fields in the case type's order, the Human Task it waits on,
the action that task carries, its linked records and its newest activity. The page joins nothing in the browser.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and the demo seed | `make db-up`; the use-case stack seeds itself |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James saves and publishes a fee-dispute workflow (open a `complaint` case, ask a person to approve waiving the fee, then call the waive tool) and starts a run | The run waits on its Human Task |
| 2 | Priya, who runs Operations, opens the case | The header shows the subject, status, priority, owner, team, both clocks and the next action linking to the task; About lists the fields in the complaint type's order with the amount as the server formatted it; one case request feeds the page and no reviews, runs or files list is read |
| 3 | She reads what it waits on and what is drafted | Waiting on someone lists the task, linking to its own page; Drafted actions lists the waive call as waiting on its task |
| 4 | She reads the rail and the activity | Linked records list the run; Details names the workflow; Recent activity reads in sentences with names; View all opens Activity filtered to the case |
| 5 | She approves the task where its link opens it and returns to the case | Nothing waits; the drafted action reads Approved; no next action |
| 6 | The page at 400px | Nothing scrolls sideways |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-256-ui.mjs` | passing |
