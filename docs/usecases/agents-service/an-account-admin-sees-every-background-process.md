# An account admin sees every background process and what it did

Status: passing. Id: `uc-516`. Service: `agents-service`. Layers: ui. Card: an earlier change.

An account admin opens Govern > Background and sees every listed background process with its state, last run and
last error, and the latest jobs each did for a team. A builder is told the page is for account admins, and the API
answers them 404. Stopping the workflow worker turns it late and then stopped in `/health/background`, the source
`make health` and the staging check read. A file deleted in Operations starts the purge event workflow; its job shows
on the page with the team's name and in Operations' Activity as a background job, and not in another team's.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| platform-service with the demo people, files-service, agents-service and the console on the run's own ports | started by the script (`withUiStack`, demo) |
| A workflow worker the script starts and stops | `stack.startWorker()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru Kamau (an Admin in every team) opens Govern > Background | Every process on `ops_store.background.PROCESSES` has a row; the sweeper reads Running (the run's stack starts no timer poller, so it reads Not reported) |
| 2 | James Richardson (a builder) opens the same page | The page says only an account admin sees background processes; `GET /v1/background` answers him 404 |
| 3 | The script starts a worker, then stops it | The workflow worker reads running, then late after two gaps (20 s) and stopped after five (50 s) in `/health/background` |
| 4 | James uploads a file in Operations and deletes it | The purge event workflow's job is on Wanjiru's page with team Operations, in James's Activity filtered to background jobs, and not in Nadia Petrov's (Security) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-516-ui.mjs` | passing |

## Non-vacuous check

Check 3 fails with the worker's heartbeat removed from `packages/ops_engine/src/ops_engine/worker.py` (no `beat`):
the workflow worker reads not reported and never running.
