# Write tool pauses and approval resumes with step-up

Status: current. Id: `uc-002`. Service: `agents-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Ask `ag_fraud` to "Place a 24-hour hold on wire W-88213" | An approval widget, pending, `movesMoney: true`, routed to Fraud Operations; the tool has not run |
| 2 | Approve without a step-up token (`POST .../widgets/{id}/actions`) | 422, message names step-up |
| 3 | Approve with a step-up token | 200, state `approved` |
| 4 | Approve again | 409 |
| 5 | Read the thread | The run resumed: the last reply says the hold is in place and the tool call succeeded with an `NB-` reference |
| 6 | ui: in the console chat, send the same request, click Approve, enter the password and authenticator code in Confirm it is you | The step-up dialog appears before the decision; after it, the approval toast and the continuation "The hold is in place." show in the thread |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-002-api.py` | passing |
| ui | `agents-service/scripts/test-uc-002-ui.mjs` | passing |

## Non-vacuous check

`approve without step-up is refused (422)` in the api script, and in the ui script `step-up dialog shown before the approval is sent`: without step-up enforcement the first approve would succeed and both fail.
