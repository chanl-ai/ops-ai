# A reviewer takes a workflow Human Task and sees its deadline

Status: passing. Id: `uc-225`. Service: `agents-service`. Layers: ui. Card: an earlier change.

A workflow's review step waits in Human Tasks with the time left before its deadline. A reviewer takes it with Assign to
me and finds it under Assigned to me; the person who started the run may not decide it, so may not take it either.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The demo stack on the run's own ports, with a worker | the script's `withUiStack({ platform, demo })` and `startWorker` |
| A run waiting at a review step | the faxed notice of uc-224, read below the floor, stops at Check the read |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts `mail_document` on the notice | The run waits at `check`; its review has minutes left (the workspace's reviewSlaHours) and no assignee |
| 2 | Maya opens Human Tasks | The row shows "Nh Nm left"; Assigned to me shows 0 |
| 3 | She selects the row and presses Assign to me | The route answers it updated; Assigned to me shows 1 and lists it; the sheet says "Assigned to m.okafor@…" |
| 4 | James asks to take it through the API | Skipped: only someone who may decide it assigns it |
| 5 | — | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-225-ui.mjs` | passing, `ISOLATED=1 make usecase-test UC=uc-225 LAYER=ui` (2026-10-18) |

## Non-vacuous check

The route's own tests (services/agents-service/tests/api/test_review_assignment.py) failed all three against the
previous Assign route, which skipped every id; this use case drives the same route through the console.
