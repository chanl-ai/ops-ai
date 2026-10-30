# A pause survives a restart

Status: current. Id: `uc-005`. Service: `agents-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start the service, run `complex_workflow` to its review pause, note the review id | Run `interrupted`; review id present |
| 2 | Stop the service process and start a new one on the same database | Healthy |
| 3 | Read state in the new process | The same review interrupt with the same review id |
| 4 | Decide `approved` (`POST /reviews/{id}/decision`) | `send_reply` runs once; status `replied` with the original review id |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-005-api.py` | passing |
| ui | none | retired 2026-10-29: the console no longer shows the earlier workflow engine's runs; the api layer still covers it |

## Non-vacuous check

`new process sees the same review`: the second process starts with nothing in memory, so the interrupt can only come from PostgreSQL. With an in-memory checkpointer it fails.
