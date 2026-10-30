# A reviewer decides a Human Task beside a fixed decision panel

Status: current. Id: `uc-460`. Service: `console` with `agents-service`. Layers: ui. Card: an earlier change.

Human Tasks is one page: the queue grouped by case on the left, the open task's evidence beside a decision panel whose
header and Decide stay in view. The service orders and names the cases (`GET /v1/reviews?group=case`) and says which
task is next (`/place?group=case`). Every view as a table, with bulk decisions and export, is All tasks (`/reviews/all`).

## Preconditions

| Needs | How |
|---|---|
| The demo stack with a worker | `withUiStack(..., { platform: true, demo: true })`, `stack.startWorker` |
| James (builder) and Maya (approver), password `northfield-demo` | The platform seed |
| Three disputes waiting: Marcus Bell's and Jordan Whitfield's on one case, Priya Natarajan's on its own with options (customers of the fake bank) | The script saves the demo's card dispute twice (one copy offers options) and adds Jordan's run to Marcus's case |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | List open Human Tasks grouped by case | Marcus, Jordan, Priya: by deadline alone Priya would sit between the other two |
| 1 | Maya opens Human Tasks | The queue in that order under case titles, a task open beside it, the sidebar folded |
| 2 | Scroll the decision panel | Approve stays at the same place, inside the window |
| 3 | Approve Marcus's task | Confirm it's you when the task asks; the run moves on; Jordan's task (same case) opens |
| 4 | Open Priya's task, choose Decline, give a reason, decide | Each option shown as a choice; Decide changes to the chosen option's name; the run moves on |
| 5 | Reassign Jordan's task | Its assignee is the person chosen |
| 6 | Open `/reviews/{id}`, then a decided task's `?review=` | Redirected to the queue; the decided task reads "Decided by …" |
| 7 | Open All tasks | The table with its views |
| 8 | Open Cases | The sidebar is back |
| 9 | Throughout | No page error; no sideways scroll at 375 px |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-460-ui.mjs` | passing |
