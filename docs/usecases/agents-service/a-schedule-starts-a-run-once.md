# A Schedule trigger starts one run per tick key

Status: api fails at step 6 (Schedule input schema not checked on POST /v1/runs); sdk passes. Id: `uc-workflows-1`. Service: `agents-service`. Layers: api, sdk.

A morning report workflow starts on a Schedule trigger. The platform clock sends a tick with a key (the day) and its
values. A tick that is due starts one run; the same key again starts none; a tick due in an hour waits in the queue;
a tick missing a value the trigger requires starts nothing.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Monday's tick starts one report run with Monday's day | api | 1 | 1 |
| S2 | The clock delivers Monday's tick twice and only one run exists | api | 2 | 2 |
| S3 | Tuesday's tick is a new run with Tuesday's day | api | 3 | 3 |
| S4 | A tick due in an hour is held until then | api | 4 | 4 |
| S5 | Fire now without the day is refused | api | 5 | 5 |
| S6 | A tick without its day is refused | api | 6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-workflows-1 LAYER=api` |

The stack is agents-service with a workflow worker on a database the run owns, removed when the run ends. The workflow
has no tool or model step. The run makes only the workflow it needs.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish the workflow (Schedule trigger, required `day`) | Live |
| 1 | Send a due tick, key `morning-2026-11-10`, day `monday` | 202, `created` true; the run succeeds with input and output day `monday` |
| 2 | Send the same key again | 200, `created` false, the first run's id |
| 3 | Send key `morning-2026-11-11`, day `tuesday` | 202, another run id; succeeds with day `tuesday` |
| 4 | Send key `morning-2026-11-12` due in 3600 seconds | 202; the run is still `queued` with no steps after the due ones finished |
| 5 | Fire now (`POST /v1/runs/start`) with no day | 422 naming `day` |
| 6 | Send a tick (`POST /v1/runs`) with no day | 422 naming `day`, no run |
| 7 | List the workflow's runs | Steps 1, 3 and 4 are `succeeded`, `succeeded`, `queued` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-workflows-1-api.py` | steps 0 to 5 and 7 pass; step 6 fails on main |
| sdk | `agents-service/scripts/test-uc-workflows-1-sdk.py` | passing: `OpsAI.workflows.schedule`, steps 1 to 4 |
| ui | none | The schedule trigger has no screen of its own; Start run on a schedule workflow is covered by the start-by-hand use cases |

## Non-vacuous check

`2 the same tick key again starts no second run`: with the unique run key removed from the start row, step 2 answers
202 with a new run id and fails. `4`: with the due time ignored, the run finishes and the status is not `queued`.
