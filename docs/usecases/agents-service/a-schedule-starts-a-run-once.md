# A Schedule trigger starts one run per tick key, and a saved schedule starts one run per slot

Status: see the acceptance layers below. Id: `uc-workflows-1`. Service: `agents-service`. Layers: api, sdk, cli.

A morning report workflow starts on a Schedule trigger. A caller sends a tick with a key (the day) and its values. A
tick that is due starts one run; the same key again starts none; a tick due in an hour waits in the queue; a tick
missing a value the trigger requires starts nothing. A second workflow has a schedule saved on its trigger: the
worker's schedule clock starts one run at each slot, keyed by the slot and started by the schedule, with no caller.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Monday's tick starts one report run with Monday's day | api | 1 | 1 |
| S2 | The clock delivers Monday's tick twice and only one run exists | api | 2 | 2 |
| S3 | Tuesday's tick is a new run with Tuesday's day | api | 3 | 3 |
| S4 | A tick due in an hour is held until then | api | 4 | 4 |
| S5 | Fire now without the day is refused | api | 5 | 5 |
| S6 | A tick without its day is refused | api | 6 | 6 |
| S7 | A schedule saved on a live workflow applies at once and the clock starts one run at its next slot | api | 8-10 | 9 |
| S8 | The SDK previews, saves and shows a rule in the API's words, and a rule under the floor is refused | sdk | 11 | 11 |
| S9 | `opsai workflows schedule` previews, saves, shows and clears, and exits non-zero under the floor | cli | 12 | 12 |
| S10 | A daily rule in a zone whose clocks change has one slot on each such day, at its local time | api | 13 | 13 |
| S11 | A rule with a field its kind does not have is refused naming the field | api | 14 | 14 |
| S12 | A schedule save, change and clear each reach the account's audit log with the old and new schedule in words | cli | 17 | 17 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-workflows-1 LAYER=api` (also `sdk`, `cli`) |
| A one-minute floor | The api layer sets `OPS_SCHEDULE_FLOOR_MINUTES=1` on agents-service and the worker, so the clock is seen within two minutes |

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
| 8 | Before the worker starts, save and publish a second workflow and save "every 1 minute, UTC" on its trigger | 200, words "Every minute from 00:00, UTC", three next runs |
| 9 | Wait for the worker's schedule clock (its first pass sees the schedule, the next starts the slot) | One run, `succeeded`, created by `trigger:schedule:<workflow>`, input `dueAt` on the minute |
| 10 | Read the schedule | Last outcome `ran` (or `late`), last slot at or after that run's `dueAt` |
| 11 | sdk: preview, save and show "every 15 minutes from 07:00, Europe/London"; save every 2 minutes | One set of words and next runs; the second save raises naming `every` |
| 12 | cli: `opsai workflows schedule preview`, `save`, `show`, a save under the floor, `clear`, `show` | Exit 0 with the server's words; non-zero naming `every`; exit 0; non-zero after clear |
| 13 | Preview a daily 01:30 rule in Europe/London from the days before the spring and autumn clock changes (`after`) | Next runs 28 Mar 01:30, 29 Mar 01:00 (the first minute after the gap), 30 Mar 00:30 UTC; 24 Oct 00:30, 25 Oct 00:30 (the first 01:30 only), 26 Oct 01:30 UTC |
| 14 | Preview a daily rule written with `at` instead of `time` | 422 naming `at` |
| 17 | cli, with platform-service and the worker's relay: save, change and clear a schedule, then read `GET /v1/audit` as an admin | Three entries for the workflow: "Set the schedule of…", "Changed the schedule of… from… to…", "Cleared the schedule of…; it was…" |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-workflows-1-api.py` | steps 0 to 10, with the clock |
| sdk | `agents-service/scripts/test-uc-workflows-1-sdk.py` | steps 1 to 4 (`OpsAI.workflows.schedule`) and 11 (`OpsAI.workflows.schedules`) |
| cli | `agents-service/scripts/test-uc-workflows-1-cli.py` | step 12 |
| ui | none | The schedule trigger has no screen of its own; Start run on a schedule workflow is covered by the start-by-hand use cases |

## Non-vacuous check

`2 the same tick key again starts no second run`: with the unique run key removed from the start row, step 2 answers
202 with a new run id and fails. `4`: with the due time ignored, the run finishes and the status is not `queued`. `9` depends on the line in
`api/worker.py` that starts the clock; with it removed, `tests/engine/test_schedule_clock_db.py` fails with no clock
heartbeat (this page's step was not run with it removed). With the missed threshold at half the interval alone, step 9
failed with outcome `missed`, which is how that defect was found.
