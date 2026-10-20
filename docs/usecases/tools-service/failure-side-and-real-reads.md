# A failed tool call says which side failed, and a test call reaches the real system

Status: current. Id: `uc-038`. Service: `tools-service`. Layers: api. Live: runs only with `OPS_LIVE_EGRESS=1`.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Outbound https to postman-echo.com | `OPS_LIVE_EGRESS=1`; without it the use case reports skipped and passes, so offline CI is not failed |

The script starts tools-service on its own database and OPA, lists postman-echo.com and an unresolvable `.invalid`
host on the egress allow-list, and publishes one read module on each.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call the postman-echo.com read through `/v1/calls` | Allowed and reached: the echo of the order, or an upstream failure reported with the upstream's status and `side: upstream`; never a failure on our side |
| 1b | Call it again | postman-echo's echo of the request has no `cookie` header: the session cookie it set on the first answer was not kept |
| 2 | Call the read on the unresolvable host | `CONNECT_FAILED`, `side: ours` |
| 3 | Read `/v1/executions` for the run | The failed call shows `failureSide: ours` and `errorCode: CONNECT_FAILED`; no message carries an address |
| 4 | Run the postman-echo.com read from the test console's "Test environment" as an approved workflow | `stubbed: false`, `reachedHost: postman-echo.com`, a real latency |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-038-api.py` | passing |

## Non-vacuous check

`the test console's Test environment read reached postman-echo.com, not the stub`: before c-038 the sandbox target
answered from the stub with no host, and `stubbed` did not exist.
