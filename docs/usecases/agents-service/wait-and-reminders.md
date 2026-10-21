# A workflow waits for a time or date and reminds a person

Status: passing (2026-10-19). Id: `uc-403`. Service: `agents-service`. Layers: api. Card: c-277.

A court order notice gives the bank a date to respond by. The workflow keeps that date itself: a Wait step pauses the run for
a duration or until a date read from an earlier step, and goes on by `out` when the time has passed. A date already
past goes on at once; a value that is not a date leaves by `error` with the value named, so a run never waits for ever
on bad data. A Human review that a person has not decided yet is reminded every N hours: each reminder is a
`task.reminder` service event, listed in Activity, and the review keeps waiting until someone decides it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-403 LAYER=api ISOLATED=1` |

The stack is agents-service with a workflow worker polling every 0.2 seconds; no workflow has a tool or model step.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish three workflows: a two-second Wait, a Wait until `$.input.respondBy`, a review reminded about every two seconds | All live |
| 1 | Start the two-second Wait | The run reads waiting, then ends `done` no sooner than two seconds after it started |
| 2 | Start the date Wait with `2020-01-31`, then with `next Friday` | The first ends `due` at once; the second ends `not_a_date`, its step output naming `next Friday` |
| 3 | Start the reminded review and leave it | At least two reminder rows in Activity (`kind=reminder`), waiting, and the run still waiting |
| 4 | Decide the review, then wait four seconds | The run ends approved and no reminder is added |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-403-api.py` | passing |

## Non-vacuous check

`services/agents-service/tests/engine/test_wait_and_reminders.py` fails when the worker queues no wake-up for a Wait
(the run waits for ever), when a past date pauses instead of going on, when the next reminder is not queued, and when a
reminder is taken as a resume.

## What this does not cover

The Schedule trigger (c-370). What a reminder does next, an email or a reassignment, is a workflow a team adds for the
`task.reminder` event; none is shipped. Reminders on steps other than Human review.
