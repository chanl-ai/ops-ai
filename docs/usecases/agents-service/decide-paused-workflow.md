# A paused workflow is decided from the console

Status: current. Id: `uc-008`. Service: `agents-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, console :3018 (ISOLATED=1 adds 1000) |

The scripts start the agents service on the scripted model. The ui script also starts the console with
`NEXT_PUBLIC_OPS_CASES_API_URL` pointing Cases runs and Reviews at it; every other area stays on the mock.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start uc-004's dispute workflow on the first dispute email | The run pauses at the review |
| 2 | Cases, Needs a person | A row for the run with state Waiting on a person |
| 3 | Open the row | The run sheet lists the node steps (extract three times, draft, grade) with the review step waiting |
| 4 | Reviews, open the review and approve | No step-up is asked: the reply is a `write` one person approves. The decision is accepted |
| 5 | Decide the same review again (api) | Accepted, with no second resume |
| 6 | Cases | The row is Done and has left Needs a person; `send_reply` ran once |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-008-api.py` | passing |
| ui | none | retired 2026-10-29: the console no longer shows the earlier workflow engine's runs; the api layer still covers it |

## Non-vacuous check

`send_reply ran exactly once` together with `repeated decision accepted without a second resume`: a facade that
resumed on every decide would send the reply twice and fail both. In the ui script, `the row finished` fails if the
decision is recorded but the thread never resumes.
