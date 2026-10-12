# Complex workflow with fan-out, grade loop, review pause and send

Status: current. Id: `uc-004`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create a `complex_workflow` thread and run it on the first dispute email with the first grade forced to 0.4 | `extract` runs three times (one per attachment), `draft` and `grade` twice, and the run ends `interrupted` |
| 2 | Read state | The interrupt is a review; nothing has been sent |
| 3 | Resume it on the run stream | 409 `resume_via_review`: a review is decided in Reviews |
| 4 | `POST /reviews/{id}/decision` `approved`, then the same again | Both 200; `send_reply` runs once |
| 5 | Read state | Status `replied`, an `OUT-` outbound id |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-004-api.py` | passing |

## Non-vacuous check

`repeated decision accepted without a second resume` together with `send_reply ran exactly once`: a decide that
resumed twice, or a graph that re-ran on resume, would send twice and fail both.
