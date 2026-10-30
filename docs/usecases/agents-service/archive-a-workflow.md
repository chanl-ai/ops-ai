# A builder archives a workflow and restores it

Status: passing (2026-10-19). Id: `uc-252`. Service: `agents-service`. Layers: api, ui. Card: an earlier change.

Old and test workflows pile up on the Workflows list. A builder archives one they no longer need: it starts no run of
any mode, a trigger no longer serves it, and it leaves both workflow lists, while its versions and runs are kept.
Restoring it brings back the version that served it, live or paused. Who may delete the workflow may archive it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-252 LAYER=api ISOLATED=1` |

The stack is agents-service with a workflow worker, on the scripted model.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish a one-step workflow | 201, the version goes live |
| 1 | Start it | The run succeeds |
| 2 | `POST /v1/workflows/definitions/{id}/archive`, then start it live and as a test | `archivedAt` set; both starts 409 `workflow_archived` |
| 3 | List workflows, both lists, then with `status=archived` | Left out of both lists; listed when asked for; its run still reads |
| 4 | `POST /v1/workflows/definitions/{id}/restore`, start it | `archivedAt` empty, live version 1 again, the start is accepted |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-252-api.py` | passing |
| ui | `agents-service/scripts/test-uc-252-ui.mjs` | passing (2026-10-28): archived, the workflow leaves the Workflows page and Start run while its run still opens; restored, it is back |

## Non-vacuous check

With the archived check removed from `RunStore.create`, the unit tests in `tests/api/test_workflow_archive.py` fail
(a test run and a child run of an archived workflow start); with the list filter removed, the archived workflow stays
on the definitions list.

## What this does not cover

The Workflows page's Archive and Restore actions are opsai-worker-ui's, on this API.
