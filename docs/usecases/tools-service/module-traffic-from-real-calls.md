# A module's call counts and activity come from real calls

Status: current. Id: `uc-042`. Service: `tools-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The fake bank on https | `docs/usecases/lib/fake_bank_https.py`, started by the script |
| agents-service's workflows | The script starts agents-service; approvals name `dispute_email` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a module with a read that succeeds, a read the bank answers 404, and a write; publish a second module | both list 0 calls, 0 error rate, 0 ms p95 |
| 2 | Call the good read three times, the failing read once, the write once with no approval, through `/v1/calls` | 200 ×4; the write is refused |
| 3 | List modules | the first shows 4 calls, error rate 0.25, p95 above 0; the second still 0 |
| 4 | Open the first module | operations count 3/0, 1/1.0 and 0 (a refusal is not a call) |
| 5 | Read its activity | 14 days; today 4 calls and 1 error, the rest 0; `denied24h` 1 |
| 6 | Approve a 30-day test approval, then a 5-day one | approved, then expiring |

Counts cover calls that reached the system (outcome `ok` or `error`) in the last 24 hours. Refusals are counted
as denied; replays return the first call's result and count as nothing. The aggregate is one SQL query over
`gateway_calls` (`CallLog.traffic`, GROUPING SETS for each operation and the module). A module's p95 is over all of
its calls. Days are UTC.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-042-api.py` | passing |

## Non-vacuous check

Step 1 pairs with step 3, step 4's refused write with step 5's denied count, and step 6's two approvals with each
other. `services/tools-service/tests/test_traffic.py` covers the 24-hour window and the module p95 with backdated rows,
which the api layer cannot make.
