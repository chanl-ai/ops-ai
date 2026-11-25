# A provider type added as a file shows in the add list

Status: passing. Id: `uc-791`. Service: `models-service`. Layers: api, ui.

Short title: A provider type added as a file shows in the add list

## Story

As an operator of an install, I want to add a model provider by dropping one JSON entry into a folder so that account
admins can connect it without waiting for a release.

## People

| Person | Role | Does what |
|---|---|---|
| Nadia Petrov | Account admin (Security team) | Reads the provider types and makes a connection of the new one |
| The operator | Runs the install | Puts the entry in the folder `OPS_MODELS_PROVIDER_REGISTRY_EXTRA` names |

## In this example

In this example an operator adds "Acme LLM", an endpoint that speaks OpenAI's chat API, as one file. It assumes the
entry names the existing `openai-compatible` adapter, so no code changes.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An entry added as one JSON file shows in the admin's list of provider types, beside the built-in ones | api | 1 | 1 |
| S2 | The admin makes a connection of the new type with no code change | api | 2 | 2 |
| S4 | In the console's Connect a provider dialog the added type is found by search, draws the fields its JSON entry names with its token masked, and saves as a connection; the key test of a loopback endpoint is refused | ui | 4-5 | 4 |
| S3 | An entry naming an adapter no code registers stops the service from starting, rather than failing on a call | api | 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| An extra registry folder | The script writes one to a temporary folder and passes it as `OPS_MODELS_PROVIDER_REGISTRY_EXTRA` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start models-service with the folder; the admin reads `GET /v1/models/provider-types` | Acme LLM is listed with OpenAI, Anthropic, Google Gemini, Azure OpenAI, Amazon Bedrock and OpenAI-compatible URL |
| 2 | The admin posts a connection of type `acme-llm` | 201, and the connection list shows it with that type |
| 3 | Start models-service with an entry whose adapter is `acme-sdk` | The service exits before it is healthy, naming the entry and the adapter |
| 4 | Sam opens Connect a provider in the unchanged console and searches acme | Acme LLM is offered; the form shows the entry's Acme endpoint and Acme token, the token masked |
| 5 | Sam names it, gives a loopback endpoint and a token, and connects | The connection is saved and listed as Acme LLM; the key test is refused for the loopback address (a key is only tested against a public address), and no page shows the token |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `models-service/scripts/test-uc-791-api.py` | passing, `make usecase-test UC=uc-791 LAYER=api` (2026-11-25) |
| ui | `models-service/scripts/test-uc-791-ui.mjs` | passing, `make usecase-test UC=uc-791 LAYER=ui` |

## Non-vacuous check

Step 1: with the extra folder left out of the registry load, the list lacks Acme LLM and the check fails
(`tests/test_provider_registry.py` was seen failing that way). Step 3 fails when the adapter check is removed.
