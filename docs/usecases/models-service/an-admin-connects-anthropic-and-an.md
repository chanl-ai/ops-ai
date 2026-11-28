# An admin connects Anthropic and an agent's model settings reach its chat

Status: passing. Id: `uc-792`. Service: `models-service`. Layers: api, ui.

Short title: An admin connects Anthropic and an agent's model settings reach its chat

## Story

As an account admin, I want to connect Anthropic and name a model "fast" so that builders pick it on their agents
and set only the settings that model takes, and their agents' chats run with them.

## People

| Person | Role | Does what |
|---|---|---|
| Nadia Petrov | Account admin (Security team) | Connects Anthropic with its key, tests the key, maps the alias |
| Sam Adeyemi | Account admin (Security team), the console's sign-in for the ui layer | The same, through Settings, Models |
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
| S6 | On Settings, Models, the admin connects Anthropic from the searched list with a masked key, sees the test refused for a loopback address, and reads the catalog's models | ui | 8-10 | 8 |
| S7 | The admin makes alias fast from that connection's catalog and the Aliases list shows it | ui | 11 | 11 |
| S8 | The builder picks the alias and sees only the five settings Claude Haiku takes, each on its default | ui | 12 | 12 |
| S9 | A setting is changed, reset on its own and saved with the agent, and the agent's chat reaches the provider with it | ui | 13-14 | 14 |
| S10 | A builder is offered no Models page and cannot list a connection | ui | 15 | 15 |

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
| 4a | The admin re-points the alias | 201; the alias has versions 1 and 2. A builder's re-point is 403 `admin_only` (ui step 15, platform sign-in) |
| 5 | The builder reads `GET /v1/model-aliases/{alias}/knobs` on agents-service | Exactly temperature, top p, top k, thinking budget and longest answer; temperature's default is 1 and maximum 1 |
| 6 | The builder makes an agent on the alias and saves temperature 1.6, then temperature 0.4, top k 30 and a thinking budget of 2,000 | The first is 422 naming Temperature; the second is saved and read back |
| 7 | The builder tests the agent | 200; the fake received temperature 0.4, `top_k` 30 and `thinking: {type: enabled, budget_tokens: 2000}` |
| 8 | Sam opens Settings, Models, Connections, picks Anthropic from the searched provider list, names it and gives the fake as base URL and the key | The form is the registry's two fields, the key is masked, and the saved connection's test is refused for the loopback address in the dialog |
| 9 | Sam closes the dialog | The list shows the connection as Anthropic with its endpoint and the key name; no page shows the key |
| 10 | Sam opens the row's Models | The catalog's Claude models show with what each can do |
| 11 | Sam makes alias `fast-…` from the connection's catalog, cleared for Confidential | The Aliases list shows it with connection, model and clearance |
| 11b | On a phone, 390 wide, Sam opens Aliases and Connections | Each row stacks its details under the name; neither the page nor a table scrolls sideways |
| 12 | James picks the alias in the agent's Model dialog | Exactly Temperature, Top p, Top k, Thinking budget and Longest answer show, each marked Default |
| 13 | James sets 0.4, top k 99 then resets it and sets 30, a 2,000 thinking budget, then 1.6 and Done, then 0.4 and Done | Reset empties its field; 1.6 keeps the dialog open and saves nothing; the agent then saves exactly those three settings |
| 14 | James tests the agent | The fake received the saved settings |
| 15 | James opens Connections | The page says only an account admin changes models, the rail has no Connections link and the API answers 403 |
| 16 | The admin lists the aliases on models-service after step 6 | Alias `fast-…` says it is used by 1 agent (`usedBy: 1`), counted by agents-service |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `models-service/scripts/test-uc-792-api.py` | passing, `make usecase-test UC=uc-792 LAYER=api` (2026-11-25) |
| ui | `models-service/scripts/test-uc-792-ui.mjs` | passing, `make usecase-test UC=uc-792 LAYER=ui` (2026-11-25) |

## Non-vacuous check

Step 7: with the saved settings left out of the turn's settings, the request reaches the provider without them;
`services/agents-service/tests/unit/test_agent_model_settings_call.py` was seen failing that way. Step 6 fails when the
save is not checked against the alias's knobs (`tests/api/test_agent_model_settings_save.py` was seen failing that way).
Step 16 fails when the count is not asked of agents-service (it reads null). Step 12 fails when the dialog draws a fixed list of settings instead of the alias's knobs; step 13 fails when Reset stores the default as a value (the saved settings then hold four keys).
