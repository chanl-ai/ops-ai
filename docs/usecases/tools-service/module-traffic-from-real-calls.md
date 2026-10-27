# A module's call counts and activity come from real calls

Status: current. Id: `uc-042`. Service: `tools-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The fake bank on https | `docs/usecases/lib/fake_bank_https.py`, started by the script |
| agents-service | The script starts agents-service, which decides the module's security review |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a module with a read that succeeds, a read the bank answers 404, and a write; publish a second module | both list 0 calls, 0 error rate, 0 ms p95 |
| 2 | Call the good read three times, the failing read once, the write once with no approval, through `/v1/calls` | 200 ×4; the write is refused |
| 2b | Send the write with an approval token, then the same write again | the first runs; the second answers with `replayOf` the first call |
| 3 | List modules | the first shows 5 calls, error rate 0.2, p95 above 0; the second still 0 |
| 4 | Open the first module | operations count 3/0, 1/1.0 and 1/0 (the write's run; its refusal and replay are not calls) |
| 5 | Read its activity | 14 days; today 5 calls and 1 error, the rest 0; `denied24h` 1 |
| 5b | List `/v1/executions` for the module and add the rows up by status | ok + error rows equal the calls, error rows the errors, denied rows `denied24h`; the replay is listed as `replayed` with `replayOf` |

Counts cover calls that reached the system (outcome `ok` or `error`) in the last 24 hours. Refusals, including a write
refused because the same one is still running (409), are counted as denied and listed as `denied`; a replay returns
the first call's result, counts as nothing, and is listed as `replayed` with the call it repeated. The aggregate is one SQL query over
`gateway_calls` (`CallLog.traffic`, GROUPING SETS for each operation and the module). A module's p95 is over all of
its calls. Days are UTC.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-042-api.py` | passing |

## Non-vacuous check

Step 1 pairs with step 3, and step 4's refused write with step 5's denied count. A module's approval state (approved,
then expiring as its end nears) left this use case when a workflow's access request moved to its system workflow in
Human Tasks (c-257): `services/tools-service/tests/test_tool_grants.py` checks the state, and uc-053 the grant. `services/tools-service/tests/test_traffic.py` covers the 24-hour window and the module p95 with backdated rows,
which the api layer cannot make.
