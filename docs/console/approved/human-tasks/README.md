# Human Tasks, as approved

Status: current. The inbox layout was approved on 2026-11-25 and replaces layout A (approved 2026-10-23, kept
below as history). The real Human Tasks page is built to match it; a difference is a defect unless a new version is
approved here.

## The inbox (2026-11-25)

The list is a column of 23 rem (24 rem from 1280 px) with the three views as full-width tabs, a search the server
runs (title, customer, case name), the table view as an icon button, and the tasks grouped under their case. The open
task fills the rest: a bar with up and down through the queue and a More menu (Assign to me, Assign or Reassign,
Open case, each shown only when the server says the person may do it), then the kind, case, time left and assignee,
the question, the amount in the step's own currency, one pill style for status, risk and approvals. Below 1024 px the
task opens over the list from the bottom and closes back to the same place. A person who may not decide sees the task
with no menu. The page's big title block is dropped; the top bar names the page.

Not built yet, against the mock: Approve and Reject in the pinned bar (they stay in the decision form at the foot of
the task), Return to agent in More (it stays in the form, and the server offers it only where the decision route takes
it), and sample-data cases and step values in the console's mock fixtures.

Screenshots are written by uc-460's ui layer (`queue-*`, `option-step-*`, `search-none-*`, `member-*`).

## Layout A (2026-10-23, history)

Approved build: console at `7eae5211`, route `/preview/human-tasks?layout=a` on sample data, deleted once
`/reviews` drew it; the screenshots below are the approved record. The real page is walked by uc-460
(`docs/usecases/console/human-tasks-queue.md`).

| Screen | 1280 px | 400 px |
|---|---|---|
| The queue grouped by case beside the open task: the evidence with its read fields boxed, the decision panel with the facts, the choices and Decide | [queue-and-task-1280](queue-and-task-1280.png) | [queue-400](queue-400.png), [task-400](task-400.png) |
| Confirm it's you before a decision that moves money | [confirm-1280](confirm-1280.png) | |

Not built from the mock, by decision: Undo after a decision, Ask for more information, and
per-person tabs on one notice.
