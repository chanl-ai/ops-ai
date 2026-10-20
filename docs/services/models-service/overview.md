# models-service

Status: first slice built, 2026-10-11; checked 2026-10-16. `services/models-service` (`ops_models`), on :8730, with
its own migration chain (`alembic_version_models`). Opt-in: `make up` does not start it, and callers use it only when
`OPS_MODELS_URL` is set. Tests: `services/models-service/tests` (scripted provider; no real model calls).
Design: ADR ai-gateway (the key-and-budget service in front of the data-plane gateway), service map row
`models-service`, console plan `docs/plan/ai-gateway-console.md`.

## What it does

Every model call goes through one OpenAI-compatible endpoint that knows which key is calling, what that key may
still spend, and which bank alias it asked for. Workers hold a model key, never a provider credential.

| Part | Detail |
|---|---|
| Provider connections | `openai-compatible`, `anthropic` (registered, not served yet) or `scripted`. A connection stores a credential's name (`keyRef`); the value comes from `OPS_MODEL_PROVIDER_KEYS` and never reaches the database |
| Aliases | `bank-standard`, `bank-reasoning`, `bank-embed` in the seed, on the scripted connection; `default` (the runtime's default alias) on connection `openai-local` when `OPS_MODELS_FAKE_OPENAI_URL` is set. Versions are immutable; the newest current version serves. Each version names its provider model, its cleared sensitivity (public < internal < confidential < restricted), whether it is cleared for images and files (`images`, off unless set, models 0006) and its price per million tokens |
| Keys | One per identity: `agent:<id>`, `workflow:<id>`, `user:<email>`, `purpose:<name>`, with a budget, spend, a calls-per-minute limit, an expiry and a status. Only a hash of the secret is stored; it is shown once at issue and at rotation |
| Rotation | `POST /v1/models/keys/{id}/rotate` issues a new secret and keeps the previous one valid for the overlap (`OPS_MODEL_KEY_OVERLAP_SECONDS`, 900 by default) |
| Admission | `POST /v1/models/admit {keyId, alias?, estimatedTokens?}`: 200, or 429 `key_budget_exhausted`, 403 `key_expired`, `key_revoked`, `key_not_registered`. An unregistered identity is refused: every caller that spends needs a key |
| Completions | `POST /v1/models/chat/completions`, OpenAI's request and response shape so OpenAI clients call it with a base URL of `/v1/models`. Authenticated by the key's secret, with optional `X-Data-Sensitivity`, `X-Run-Id`, `X-Step-Id`, `X-Thread-Id`, `X-Request-Hash`. Checks in order: key status, expiry and budget, rate limit, alias, cleared sensitivity, then image clearance: a request with any content part that is not text (an image, a file, or a kind not yet named) is refused 403 `images_not_cleared` by a version not cleared, and every call row counts those parts (`images`); then the provider call, the cost from the alias version's price (`ops_metering`) and the spend. `stream: true` answers SSE chunks; `tools` reach the provider and `tool_calls` come back, whole or as deltas. Refusals use the platform error envelope, which OpenAI clients read as `error.code` |
| Call log | `model_call_log`, one row per authenticated completion, denials included: key, alias and version, provider model, tokens, cost, latency, outcome and reason, run, step and thread ids, and the caller's request hash. No prompt or completion text. `GET /v1/models/calls?keyId&alias&outcome&threadId` returns rows and totals per key |

Admin and admission routes take the service token; a person reaches them through platform-gateway later.

agents-service is the first caller: with `OPS_MODELS_URL` and `OPS_MODELS_KEY` set, every agent turn comes here on
its agent's alias with agents-service's key (`agents:dev` in the dev seed), and inside a graph run with the thread,
run, step and request hash as headers ([runtime.md](../../architecture/runtime.md#which-model-a-turn-runs-on)).
Use case uc-028 drives the whole path.

## Real or fake model, by connection

Code never chooses between a real and a fake model. An alias names a connection, and the connection's base URL decides
where the call goes. `services/models-service/scripts/fake_openai` is a stand-in OpenAI chat API (`POST
/v1/chat/completions` streamed or not, `GET /v1/models`, no key): with tools offered it answers a tool call from rules
in `<dir>/script.json` (`{"rules": [{"when": "<regex on the user's message>", "tool": "...", "arguments": {}}]}`),
otherwise text naming the agent from the system prompt and the gist of the last message.

| Step | Command or call |
|---|---|
| Start the fake | `cd services/models-service/scripts && uv run --project .. python -m fake_openai .run/fake-openai` (port `FAKE_OPENAI_PORT`, else `port` in script.json, else 8746); it prints the URL to set |
| Script it | `<folder>/script.json` rules turn a prompt into a tool call, including Pydantic AI's `final_result` output tool for a structured call; the committed set is `services/models-service/seed/demo-fake-openai/script.json` (the levy notice's persons, c-057, and the banker demo's rules, c-058); `.run/fake-openai/script.json` is a copy of it: copy it there and restart the fake, which reads the file once at start |
| Seed against it | `OPS_MODELS_FAKE_OPENAI_URL=http://127.0.0.1:8746/v1` on models-service in dev: the seed adds connection `openai-local` (openai-compatible, that base URL) and alias `default` on it. Rows that exist are left alone |
| Point `default` at OpenAI | `PUT /v1/models/providers/openai-local {"baseUrl": "https://api.openai.com/v1", "keyRef": "openai"}` with `OPS_MODEL_PROVIDER_KEYS={"openai": "<key>"}` on models-service, and a new version of alias `default` naming the provider's model. agents-service does not change |
| Point it back at the fake | `PUT /v1/models/providers/openai-local {"baseUrl": "http://127.0.0.1:8746/v1"}` (no `keyRef`) |
| Send agents-service through it | `OPS_MODELS_URL=http://127.0.0.1:8730` and `OPS_MODELS_KEY=mk_dev_agents` (dev seed) on agents-service; it then reads no `OPENAI_API_KEY` |

The base URL includes `/v1`: the provider posts to `<baseUrl>/chat/completions`. A scripted connection cannot be
rebound (409 `provider_not_rebindable`). An unreachable base URL answers 502 `provider_error` and logs an `error` row.
Use case uc-060 drives this path, including the rebind to a closed port and back.

## Routes

| Route | Purpose |
|---|---|
| `GET, POST /v1/models/providers` | Provider connections |
| `PUT /v1/models/providers/{id}` | Rebind a connection's base URL and credential name; every alias on it follows |
| `GET, POST /v1/models/aliases` | Aliases with their current version; create an alias with version 1 |
| `GET, POST /v1/models/aliases/{name}/versions` | All versions; add one |
| `GET, POST /v1/models/keys`, `POST /v1/models/keys/{id}/rotate` | Keys without secrets; issue; rotate |
| `GET /v1/models/calls` | The metadata log with filters and per-key totals |
| `POST /v1/models/admit` | The key-admission check agents-service asks before opening a thread |
| `POST /v1/models/chat/completions` | OpenAI-compatible egress, streamed when asked |

Every route is typed; `openapi.json` is committed and `make openapi-check` (in `verify`) fails when it drifts. The tests check every JSON response against it (`ops_service_kit.contract`).

## Tests

| Failure mode | Test | Watched to fail |
|---|---|---|
| Anyone can read keys or ask admission | `test_admin_routes_are_internal` | |
| A key at its budget spends again | `test_a_key_at_its_budget_is_refused` | Yes |
| Spend never reaches the cap | `test_spend_reaches_the_cap_and_the_next_call_is_refused` | |
| An estimate above what is left is admitted | `test_an_estimate_over_what_is_left_is_refused` | |
| An expired key is accepted | `test_an_expired_key_is_refused` | Yes |
| An unregistered identity or a guessed secret is accepted | `test_an_unregistered_identity_is_refused` | |
| Confidential data reaches an alias cleared for internal | `test_an_alias_not_cleared_for_the_data_is_refused` | Yes |
| A completion logs prompt text, or more or fewer than one row | `test_a_completion_writes_one_metadata_row_and_no_prompt_text` | Yes |
| A rotated-out secret works past its overlap | `test_rotation_keeps_the_old_secret_for_the_overlap_only` | Yes |
| A key exceeds its rate limit | `test_a_key_over_its_rate_limit_is_refused` | Yes |
| An alias version changes in place, or the old one keeps serving | `test_alias_versions_are_immutable_and_the_newest_serves` | |
| A row cannot be tied to the caller's request | `test_a_call_carries_the_callers_request_hash_and_is_found_by_thread` | Yes |
| The OpenAI client cannot parse a reply, streamed or not | `test_a_text_turn_runs_through_the_openai_client` | |
| A tool turn loses its tool calls (scripted, streamed or not) | `test_a_tool_turn_carries_the_tool_call_and_its_result` | Yes |
| An openai-compatible provider never sees the tools, or its calls are dropped | `test_an_openai_compatible_provider_gets_the_tools_and_returns_the_calls` | Yes |
| An unreachable provider is a 500, or a rebind does not move the alias | uc-060 `rebinding openai-local to a closed port fails default with 502 provider_error; rebinding back restores it` | Yes |
| A refusal is retried or reaches the client as something else | `test_a_refusal_reaches_the_client_once`, `test_a_stream_is_refused_before_it_starts` | |
| A response drifts from the documented model | every test, through the contract hook | Yes |

## Gotchas

| Topic | Detail |
|---|---|
| OpenAI clients retry a 429 twice by default | A caller must set `max_retries=0`, or one over-limit request is three calls and three denied rows |
| The OpenAI SDK is typed against httpx2 | An injected client is an `httpx2.AsyncClient`; httpx's runs but fails the type check |
| The check runs before the call | A key under its cap may make one call that takes it over; the next is refused. A reservation per call would close it |
| Concurrent calls race the cap | Two calls checked at once both pass; spend is added with one `UPDATE … SET spent = spent + cost`, so it is never lost, only overshot |
| Table name | The call log is `model_call_log`: agents-service's replay ledger already has `model_calls` in the shared database |
| Prompt-free logging needs a real check | A test that looked for one late prompt fragment passed while a cut prompt was being logged; it now checks several fragments of prompt and reply |

## Not built yet

| Item | Where it goes |
|---|---|
| agents-service's KeyAdmission adapter (`/v1/models/admit` before a thread opens) and use cases uc-016, uc-017 | Next slice; turns already run through completions (uc-028) |
| Anthropic provider, retries and timeouts, failover with evidence, redaction | Later slices, per the ADR's day-one table |
| Data-plane gateway (Portkey) behind this service | Deployment |
