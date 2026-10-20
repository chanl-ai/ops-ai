# An agent runs on the model its publisher chose

Status: current. Id: `uc-028`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | agents :8790, models :8792 (ISOLATED=1 adds 1000; or set the OPS_USECASE_* ports and OPS_USECASE_DB) |

The script starts models-service on its dev seed, where every alias answers with the scripted provider, and issues a
key for this run with a limit of two calls a minute. It starts the agents service with `OPS_MODELS_URL`,
`OPS_MODELS_KEY` set to that key and `OPS_MODEL_ALIAS=bank-standard`, so turns go through models-service and no
provider key is read. No real model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create an agent on `bank-reasoning`, publish it, run its test turn | The turn reports `bank-reasoning` and the scripted reasoning reply |
| 2 | Read models-service's call log for the key | One `ok` row on `bank-reasoning`, provider model `scripted-reasoning` |
| 3 | Run a thread on the agent's graph | The run's `model_call` event and models-service's row for the thread name the same alias, request hash and token counts |
| 4 | Publish an agent naming `no-such-alias` | 422 `unknown_model_alias` |
| 5 | Run the test turn a third time inside the minute | 429 `rate_limited` |
| 6 | Read the denied rows | Exactly one, `rate_limited`: the client did not retry |
| 7 | Read every row | Each provider model is a scripted one |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-028-api.py` | passing |

## Non-vacuous check

`the test turn ran on the agent's alias, bank-reasoning, through models-service`: with the kernel's per-alias model
source removed, the turn runs on the runtime alias and reports the scripted standard reply.
