# An admin connects Anthropic and an agent's model settings reach its chat

Status: passing. Id: `uc-792`. Service: `models-service`. Layers: api.

Short title: An admin connects Anthropic and an agent's model settings reach its chat

## Story

As an account admin, I want to connect Anthropic and name a model "fast" so that builders pick it on their agents
and set only the settings that model takes, and their agents' chats run with them.

## People

| Person | Role | Does what |
|---|---|---|
| Nadia Petrov | Account admin (Security team) | Connects Anthropic with its key, tests the key, maps the alias |
| Maya Okafor | Builder in Operations | Reads the alias's settings, saves some on an agent, tests the agent |

## In this example

In this example the fake OpenAI stands in for Anthropic's OpenAI-compatible endpoint, and the alias points at Claude
Haiku 4.5, whose catalog entry takes temperature 0 to 1, top p, top k, a thinking budget and answers of up to 64,000
tokens. It assumes the committed model catalog; nothing is fetched at run time.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The admin finds Anthropic in the add list and saves a connection with its key; no reply shows the key | api | 1-2 | 2 |
| S2 | Testing the key never sends it to a loopback address | api | 3 | 3 |
| S3 | The admin maps alias fast, and a builder sees only the settings its model takes, with catalog defaults | api | 4-5 | 5 |
| S4 | A setting outside the model's range is refused naming it; settings in range are saved | api | 6 | 6 |
| S5 | The agent's chat reaches the provider with the saved settings | api | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The fake provider | `services/models-service/scripts/fake_openai`, answering only `FAKE_OPENAI_API_KEY` and keeping each chat request's settings at `GET /received` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The admin reads `GET /v1/models/provider-types` | Anthropic is listed; its `apiKey` field is marked `x-secret` |
| 2 | The admin posts an Anthropic connection with base URL the fake, key name `UC792_ANTHROPIC` and the key in `secrets` | 201; neither that reply nor the connection list holds any part of the key |
| 3 | The admin tests the key against the fake's loopback address | 422 `endpoint_refused`: a key test only goes to a public address (the success path is covered in `tests/test_provider_registry.py`) |
| 4 | The admin maps alias `fast-…` to `claude-haiku-4-5` on the connection | 201 |
| 5 | The builder reads `GET /v1/model-aliases/{alias}/knobs` on agents-service | Exactly temperature, top p, top k, thinking budget and longest answer; temperature's default is 1 and maximum 1 |
| 6 | The builder makes an agent on the alias and saves temperature 1.6, then temperature 0.4, top k 30 and a thinking budget of 2,000 | The first is 422 naming Temperature; the second is saved and read back |
| 7 | The builder tests the agent | 200; the fake received temperature 0.4, `top_k` 30 and `thinking: {type: enabled, budget_tokens: 2000}` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `models-service/scripts/test-uc-792-api.py` | passing, `make usecase-test UC=uc-792 LAYER=api` (2026-11-25) |

## Non-vacuous check

Step 7: with the saved settings left out of the turn's settings, the request reaches the provider without them;
`services/agents-service/tests/unit/test_agent_model_settings_call.py` was seen failing that way. Step 6 fails when the
save is not checked against the alias's knobs (`tests/api/test_agent_model_settings_save.py` was seen failing that way).
