# An alias reaches the fake OpenAI or the real one by its connection's base URL

Status: current. Id: `uc-060`. Service: `models-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | agents and models from the runner; the fake OpenAI on a free port the script picks |

The script starts the fake OpenAI (`services/models-service/scripts/fake_openai`) with one rule (a user message
saying "hold ... W-<n>" calls `place_wire_hold`), models-service with `OPS_MODELS_FAKE_OPENAI_URL` set to it, and the
agents service with `OPS_MODELS_URL` and `OPS_MODELS_KEY=mk_dev_agents` on its default alias `default`. No real model
is called and no model key is read.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | List providers and aliases | `openai-local` is openai-compatible at the fake's URL; `default` is bound to it |
| 2 | Complete on `default` with the dev runtime key, not streamed | 200, "Wire Fraud Sentinel on default heard: ...", usage filled |
| 3 | The same, streamed | The same text from the deltas, then a usage chunk |
| 4 | Offer `place_wire_hold` and ask to hold a wire, streamed and not | One tool call with the script's arguments, finish reason `tool_calls` |
| 5 | `PUT` openai-local to a closed port, complete, `PUT` it back, complete | 502 `provider_error`, then the fake's answer again |
| 6 | `PUT` the scripted connection | 409 `provider_not_rebindable` |
| 7 | Create and publish an agent, run its test turn | The turn reports `default` and the fake's reply |
| 8 | Read the call log for `default` | Provider model `default` on every row; outcomes `ok` and one `error` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `models-service/scripts/test-uc-060-api.py` | passing |

In the console: none yet; the AI gateway's console is planned, so the use case stays at the api layer.

## Non-vacuous check

`rebinding openai-local to a closed port fails default with 502 provider_error; rebinding back restores it`: it proves
the connection row, not code, decides where the alias goes. With the provider's transport-error mapping removed,
models-service fails the call outright and the script stops at this step (seen: exit 1 after four passes).
