# A workflow waits for its children and uses their results

Status: passing (2026-10-19). Id: `uc-402`. Service: `agents-service`. Layers: api, ui. Card: an earlier change.

A letter arrives with three attachments. The parent workflow reads each in a child run of its own, two at a time, and
then needs every child's result to go on. With Wait for them on, its Run workflow step pauses until every child has
ended and goes on by `done` with each child's outcome and output in item order. A child that fails is listed with its
outcome; it never fails the parent.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-402 LAYER=api ISOLATED=1` |

The stack is agents-service with a workflow worker; neither workflow has a tool or model step.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish the child (read one attachment) and the parent (read each, wait, two at a time) | Both live |
| 1 | Start the parent with three files, one the child cannot read | The parent succeeds; its Run workflow step went on once, by `done` |
| 2 | Read the step's output | `children` in item order: read, unreadable, read, with outputs; `counts` read 2, unreadable 1 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-402-api.py` | passing |
| ui | `agents-service/scripts/test-uc-402-ui.mjs` | passing (2026-10-28): the parent's page shows the Run workflow step once by done; its sheet lists each child's outcome in order with the counts |

## Non-vacuous check

`packages/ops_engine/tests/test_wait_for_children.py` fails when the batch size is ignored (three unfinished at once),
a failed child is dropped, the timeout is ignored, or the paused attempt is not kept (a resume after a worker died
starts a new attempt). `services/agents-service/tests/engine/test_parent_wakes_on_children.py` fails when a child's end
does not wake its waiting parent, or wakes it twice for one change.

## What this does not cover

A completion rule such as half the children, and cancelling the rest at the timeout (they keep their own state).
