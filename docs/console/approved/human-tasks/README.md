# Human Tasks, as approved

Status: current. Layout A (queue and task) was approved by the maintainers on 2026-10-23. The real Human Tasks page is
built to match it; a difference is a defect unless a new version is approved here.

Approved build: console at `7eae5211`, route `/preview/human-tasks?layout=a` on sample data, deleted by c-460 once
`/reviews` drew it; the screenshots below are the approved record. Card c-460. The real page is walked by uc-460
(`docs/usecases/console/human-tasks-queue.md`).

| Screen | 1280 px | 400 px |
|---|---|---|
| The queue grouped by case beside the open task: the evidence with its read fields boxed, the decision panel with the facts, the choices and Decide | [queue-and-task-1280](queue-and-task-1280.png) | [queue-400](queue-400.png), [task-400](task-400.png) |
| Confirm it's you before a decision that moves money | [confirm-1280](confirm-1280.png) | |

Not built from the mock, by decision (c-460 spec "Not building"): Undo after a decision, Ask for more information, and
per-person tabs on one notice.
