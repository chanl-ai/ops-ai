# A tool write without a token is refused

Status: current. Id: `uc-007`. Service: `tools-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, console :3018 (ISOLATED=1 adds 1000) |

The script starts its own services on the scripted model; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/calls` for the seeded write `update_address` (Core banking) with no approval token | 403; reasons are exactly "write needs an approval token" |
| 2 | Repeat on another step with a token minted for that thread, step, tool and input | 200; the stub answers `updated: true` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-007-api.py` | passing |

In the console: a chat write waits on an approval instead of running (uc-055's ui script, step 8; uc-086's, step 9); the gateway's refusal of a write with no token has no page of its own.

## Non-vacuous check

`same write with an approval token runs (200)` paired with the refusal: if the gateway refused everything, or OPA were down, the paired success fails and the refusal is not mistaken for policy.
