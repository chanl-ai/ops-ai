# SLA timer breach escalates

Status: current. Id: `uc-006`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a one-step workflow whose human step has `sla: 1s`, `onTimeout: escalate`, `escalateTo: supervisors`; start a thread | Run paused on the human step; a breach timer is open |
| 2 | Post to the old fire route with a service token | 404 or 405: no HTTP route fires a timer (c-168) |
| 3 | Read the review before the deadline | No change: the review stays with tier1 |
| 4 | Wait past the deadline while the timer poller runs | The review is with supervisors and marked escalated; events end `sla.breach`, `sla.escalated` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-006-api.py` | passing |

## Non-vacuous check

`before the deadline the review stays with tier1`: it proves the escalation that follows is the timer's doing. The script turns the scripted service's timer poller on (0.3 s), the one scheduler; no HTTP route fires a timer.
