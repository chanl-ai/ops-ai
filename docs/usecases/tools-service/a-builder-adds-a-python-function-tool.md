# A builder adds a Python function tool that runs sandboxed and uses a secret

Status: current. Id: `uc-531`. Service: `tools-service`, `runner-service`, `agents-service` (the workflow step). Layers: api.

## Preconditions

PostgreSQL :5477, the pinned Python build (`make -C services/runner-service wasm`, fetched by the script if missing),
and a private network address for the fake bank. The fake's `/v1/limits` answers 401 without a `rulesKey` query
value, returns a fingerprint of the key it received, and repeats the key in its answer, as a careless API might.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a bank module with `uc531_get_account` and `uc531_get_limits` (key as the `rulesKey` input); create secret `UC531_KEY` | Both reads served |
| 2 | Create a code module whose function binds both reads and `UC531_KEY`, limits 128 MB, 2 s, 5 calls; publish it | 201; the operation's executor is `code` and its secret names are stored, not values |
| 3 | Call the function with `{accountId, amount: 950}` | `{overLimit: true, leftToday: 900, balance: 1200.5}`: it read the account and the limits through `ops.call` |
| 4 | Read what the bank received and what came back | The bank got the key's value from `ops.secret` as a query value; its echo reaches the function as `[secret]` |
| 5 | Read `/v1/executions` | The function's call and each bound call are rows; no row holds the value |
| 6 | Call with `mode` unbound, socket, loop, memory | `binding_forbidden`, `function_error` (OSError), `time_limit`, `memory_limit` |
| 7 | Publish a workflow whose tool step calls the function and whose If step reads `overLimit`; run it with 950, then 100 | The runs end `over_limit`, then `within_limit` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-531-api.py` | passing |

## Non-vacuous check

Seen red before the runner was wired into the gateway: every call failed `runner_unavailable`. The sandbox's walls each
have a runner test that fails when the wall is removed (`services/runner-service/tests/test_sandbox.py`).
