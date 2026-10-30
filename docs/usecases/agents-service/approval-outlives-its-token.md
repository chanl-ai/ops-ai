# An approval outlives its token

Status: current. Id: `uc-027`. Service: `agents-service`. Layers: api.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A reviewer approves while another run holds the thread; the approval is kept and resumes later | api | 1-2 | 2 |
| S2 | When the thread is free after the approval's token expired, the run renews the token from the recorded approval and sends the reply once | api | 1-3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791 (ISOLATED=1 adds 1000) |

The script starts tools-service and the agents service with the gateway on and a one-second approval token TTL. To
make the resume late, it holds the thread's lease as another run would; nothing else bypasses the public API.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start the dispute workflow | It pauses for review |
| 2 | With the thread busy, decide `approved` | 409: the decision is recorded and resumes later |
| 3 | After the token's TTL, free the thread and decide again | 200; the gateway refuses the expired token once, the agents service renews it from the recorded approval, and the reply is sent |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-027-api.py` | passing |

## Non-vacuous check

`the late resume finished instead of failing on the expired token`: without renewal the gateway refuses the token
and the run ends in error.
