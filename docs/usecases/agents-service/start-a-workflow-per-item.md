# A workflow starts a child workflow for each item of a list

Status: current. Id: `uc-209`. Service: `agents-service` (the worker runs ops_engine). Layers: api, ui. Card: c-209.

A Start workflow step starts another workflow of the team once, or once for each item of a list (`forEach`). Each
child runs in the parent's team and mode and is keyed by the parent run, step, iteration and item, so a retry never
starts a second. In the step's input `$.item` reads the item and `$.index` its position; anywhere else the checks
refuse them.

## Preconditions

| Needs | How |
|---|---|
| The shared stack with platform sign-in and the worker | `OPS_STACK_AUTH=platform make up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James saves and publishes a child workflow and an intake that starts it for each person | Both live |
| 2 | A live run of the intake with three persons | The intake succeeds; three live children of team_ops, created by the intake's run, with each person's name and position |
| 3 | The intake's run page | The Start workflow step lists the three children in order |
| 4 | A test run of the intake | Its children are test runs |
| 5 | James saves a step that reads `$.item` with no For each | The check `item_outside_loop` names the step |

Rules are `packages/ops_engine/tests/test_start_workflow.py` and
`services/agents-service/tests/engine/test_start_workflow.py`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-209-api.py` | current |
| ui | `agents-service/scripts/test-uc-209-ui.mjs` | passing (2026-10-28): the intake's page lists its three children in order, each child's page shows its person, a test run's page lists its test child |
