# A workflow's branches join before the next step

Status: passing (2026-10-19). Id: `uc-400`. Service: `agents-service`. Layers: api, ui. Cards: c-278, c-553.

A builder runs two checks at once, a limits check and a payee screening, and decides once both are back. One step
connects to both branches, and a Join waits for them: the decision step after it runs once, with each branch's last
step output under that step's id. When an If skips the screening and goes straight to the Join, the screening's last
step is null and the decision still runs once. Without a Join, a step where two branches meet runs once per branch,
so saving that shape is warned.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-400 LAYER=api ISOLATED=1` (or `LAYER=ui`, which also signs in through platform-service) |

The stack is agents-service with a workflow worker; the workflow has no tool or model steps.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish the workflow with a Join | 201 with no warnings; the version goes live |
| 1 | Start it with `screen: true` | Succeeds; Decide runs once, reading `limits` and `screened` from the Join |
| 2 | Start it with `screen: false` | Succeeds; the Join and Decide run once; `screened` is null |
| 3 | Save the same fork with a plain step where the branches meet | 201, with a warning on that step that it runs once per branch |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-400-api.py` | passing |
| ui | `agents-service/scripts/test-uc-400-ui.mjs` | passing (2026-10-28): each run's page shows the Join and the decision once; the editor marks the plain meeting step |

## Non-vacuous check

`packages/ops_engine/tests/test_join.py` covers each piece: compiled without `defer`, the step after the Join runs
twice and the Join goes on while a branch waits on a person; without the null for a skipped branch, its step is
missing from the Join's output; without the meeting check, every step after the meeting point is warned.

## What this does not cover

Continuing when the first branch finishes, and for-each batches with keep-going (c-263). A Join waits for every step
of the run that can still run, not only its own branches.
