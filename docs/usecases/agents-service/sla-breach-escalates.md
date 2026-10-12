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
| 2 | Fire the breach timer without the service token | 401 |
| 3 | Fire it with the service token before it is due | No change: the review stays with tier1 |
| 4 | Wait past the deadline and fire it again | Accepted; the review is with supervisors and marked escalated; events end `sla.breach`, `sla.escalated` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-006-api.py` | passing |

## Non-vacuous check

`an early fire leaves the review with tier1`: it proves the fire endpoint honours the deadline, so the escalation that follows is the timer's doing and not any call to the endpoint. The timer poller is off in the scripted service, so the fire endpoint is the only path.
