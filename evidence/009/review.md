# c-009 review — second independent reviewer

Reviewer: an independent review session. Checks run on a clean `git archive HEAD` export with isolated database
(`ops_usecase_c009_rev`) and ports (agents 8890, tools 8891, models 8892, console 3118).

Gate results on clean export of HEAD:
- `make python-verify`: PASSED (models 24, agents 201, store 5)
- `make usecase-test UC=uc-028 LAYER=api`: 8/8 PASSED
- `make usecase-test UC=uc-018 LAYER=api`: 13/13 PASSED
- `make usecase-test UC=uc-019 LAYER=api`: 18/18 PASSED
- `make usecase-test UC=uc-020 LAYER=api`: 9/9 PASSED

## a5082ec — feat(models): OpenAI-shaped chat completions that stream and carry tool calls

| Field | Value |
|---|---|
| check | `make python-verify` (models-service 24 tests) |
| result | PASSED |
| rule | US1: streaming+tools through models-service, logged with request hash, 429 once with no retry |
| verdict | accept |
| defect | — |

Streaming SSE with tool-call deltas, `settle()` for spend+log, `max_retries=0` on the OpenAI client, `ScriptedProvider` handles tool calls via regex. Six tests cover text/tool turns streamed and not, refusal once, stream refused before start, older path, and openai-compatible provider round-trip.

## 3903988 — feat(models): the call log keeps the caller's request hash and is filtered by thread

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | US2: the model-call record and models-service's call log both name X with the same request hash |
| verdict | accept |
| defect | — |

Migration adds `request_hash` column and `ix_model_call_log_thread_id` index. App reads `X-Request-Hash` header, stores it, returns it in response, filters GET by `threadId`. Test proves the round-trip.

## c466de8 — feat(models): every models-service route is typed and openapi.json is gated

| Field | Value |
|---|---|
| check | `make python-verify` (includes `openapi-check`) |
| result | PASSED |
| rule | contract compliance: routes typed, openapi.json committed and gated |
| verdict | accept |
| defect | — |

Pydantic schemas for all routes, 2987-line openapi.json committed, `check_openapi.py` in verify fails when it drifts. Tests check every JSON response against the schema via `ops_service_kit.contract`.

## 0e9e827 — feat(kernel): a turn runs on its agent's alias through a model source port

| Field | Value |
|---|---|
| check | `make python-verify` (agents-service tests) |
| result | PASSED |
| rule | US2: kernel asks ModelSource for the turn's alias; max_retries=0; LedgerModel sends headers |
| verdict | accept |
| defect | — |

`KernelPorts.models` optional port; when set, `model_for(alias)` returns per-alias OpenAI model pointed at models-service with `max_retries=0`. `LedgerModel.call_headers` adds X-Thread-Id/X-Run-Id/X-Step-Id/X-Request-Hash. Tests: kernel runs on agent's alias, and one refusal is one request.

## d2efdd6 — feat(agents): with OPS_MODELS_URL and OPS_MODELS_KEY, turns run through models-service

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | US2: OPS_MODELS_URL + OPS_MODELS_KEY wires turns through models-service; without, direct path unchanged |
| verdict | accept |
| defect | — |

Settings adds `models_key: SecretStr | None`. App lifespan: both set → `ModelsServiceModels` wrapped in `LedgerSource` as `KernelPorts.models`. `LedgerSource` wraps each alias in `LedgerModel(call_headers=True)`. Integration test with `FakeModelsService` (MockTransport) proves the turn runs on the agent's alias through models-service.

## c3f951b — feat(agents): a model refusal reaches the caller with its status and code

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | US3: 429/403/404 with models-service code; other refusals 503; streamed error frame carries code; no retry |
| verdict | accept |
| defect | — |

Kernel catches `ModelHTTPError`, extracts code via `refusal_code()` (handles both `{error:{code}}` and `{code}`). `TurnResult` gains `error_status`/`error_code`. Router maps 429→429, 403→403, 404→404, else→503. Chat stream's error event carries `code`. Parametrized test: 4 refusal types, all assert `len(models.requests) == 1`.

## 081e5dd — test(agents): a re-run replays from the record and no models key keeps turns direct

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | failure modes: re-run replays (not re-calls), and no key keeps the direct path |
| verdict | accept |
| defect | — |

Two tests. (1) Same request twice in one task → second comes from the record, `len(models.requests) == 1`. (2) `models_url` without `models_key` → turns stay on scripted model, `models.requests == []`. Both guard spec failure modes.

## ba2828b — feat(agents): GET /v1/model-aliases lists the chat aliases an agent may name

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | publish-time alias check: picker lists exactly what publish accepts |
| verdict | accept |
| defect | — |

New route `GET /v1/model-aliases`, `ModelAlias` schema with clearance and prices. `ModelAliases` protocol refactored from `chat_aliases() -> set[str]` to `chat_models() -> list[dict]`. Test: picker lists bank-standard (publish 201), bank-embed absent (publish 422). openapi.json and api.md updated.

## c1f4a85 — fix(models): a streamed completion is settled before [DONE] and reports its usage

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | failure mode: stream disconnected before [DONE] still has its call row |
| verdict | accept |
| defect | — |

`settle()` moved before `[DONE]` via `asyncio.ensure_future` + `asyncio.shield`. Failed streams get a shielded error log row too. `ScriptedProvider` now emits OpenAI's usage chunk so callers meter correctly. Test asserts caller meters the same tokens models-service charged.

## 9e71c14 — test(usecases): uc-028 proves an agent runs on the model its publisher chose

| Field | Value |
|---|---|
| check | `make usecase-test UC=uc-028 LAYER=api` |
| result | 8/8 PASSED |
| rule | done_when: uc-028 passing |
| verdict | accept |
| defect | — |

107-line use case script, 8 checks: test turn reports alias, call log has key's row on alias, graph run record matches call log (alias, request hash, tokens), unknown alias refused 422, rate limit 429, one denied row (no retry), all scripted provider. Harness extended with `models_key`/`model_alias`. Non-vacuous check documented.

## c1d1095 — docs(experiments): E13, the models-service hop adds 7 ms at p50

| Field | Value |
|---|---|
| check | `make python-verify` (docs only, verify still passes) |
| result | PASSED |
| rule | supporting evidence: latency baseline for the models-service hop |
| verdict | accept |
| defect | — |

239-line experiment script: 50 scripted turns at concurrency 1 and 5, real part capped at 10 calls with owner approval. 42-line write-up with numbers, gotchas, and what it feeds. Status correctly notes real part not yet run at this commit.

## f23d68f — feat(agents): a refused reply keeps its code after a reload

| Field | Value |
|---|---|
| check | `make python-verify` |
| result | PASSED |
| rule | refusal code persists: stored message carries `errorCode` so a reload reads the same as the stream |
| verdict | accept |
| defect | — |

Moves `error_code` from `AssistantBuilder` (transient) to `ChatMessage` (persisted). Stream reads from `assistant.error_code` instead of `builder.error_code`. Test extended: reload of thread verifies `errorCode == "rate_limited"` survives.

## 2c89ed7 — docs(experiments): E13 real baseline, ten calls, the hop is lost in model variance

| Field | Value |
|---|---|
| check | docs only |
| result | PASSED |
| rule | supporting evidence: real model confirms hop is negligible |
| verdict | accept |
| defect | — |

Real model numbers (gpt-5.5): direct p50 1,703 ms, through models-service p50 1,969 ms — 266 ms difference but mean 147 ms faster. Five turns a side cannot resolve a 7 ms hop; confirmed. New gotchas added. Status updated to "holds".

## fc3f960 — docs(architecture): which model a turn runs on, and models-service's first caller

| Field | Value |
|---|---|
| check | docs only |
| result | PASSED |
| rule | design documentation: runtime.md and models-service overview updated |
| verdict | accept |
| defect | — |

Adds "Which model a turn runs on" section to runtime.md with four rules (max_retries=0, headers, graph models unwrapped, refusal keeps code). Updates models-service overview with agents-service as first caller and uc-028 reference. "Not built yet" updated to reflect completions are live. Model source added to Parts table.

## Probes — adversarial checks on a live models-service

Run against models-service on port 8892 from the clean export, database `ops_probe_c009`.

### Probe 1: disconnect before [DONE] (c1f4a85)

A streamed completion disconnected after the first SSE chunk (before `[DONE]`). The call log row and spend must
exist despite the client disconnect, and the next request on the same connection pool must succeed.

```
PROBE_MODELS_PORT=8892 uv run python probe_disconnect.py

chunks_seen_before_disconnect: 1
call_log_rows: 1
outcome: ok
alias: bank-standard
key_spent: 0.000041
second_request_status: 200
second_request_ok: True
total_rows_after_second: 2

PROBE_1_RESULT: PASSED
```

The shielded `settle()` before `[DONE]` works: the row is `ok` with spend recorded, and the pool is healthy for
the next request.

### Probe 2: rate-limited key, exactly one denied row (max_retries=0)

A key with `rateLimitPerMinute: 1`. First call succeeds (200), second is refused (429 `rate_limited`). The call
log must have exactly one denied row — proving the OpenAI client did not retry.

```
PROBE_MODELS_PORT=8892 uv run python probe_ratelimit.py

first_call_status: 200
second_call_status: 429
second_call_code: rate_limited
denied_rows_count: 1
denied_reason: rate_limited
total_rows: 2
outcomes: [('denied', 'rate_limited'), ('ok', None)]

PROBE_2_RESULT: PASSED
```

One denied row, not two or three. `max_retries=0` holds.

## Triage

Fourteen commits reviewed, two adversarial probes run. No defects found.

| Entry | Finding | Verdict |
|---|---|---|
| a5082ec streaming+tools | accept, no defect | — |
| 3903988 request hash + thread filter | accept, no defect | — |
| c466de8 typed routes, openapi gated | accept, no defect | — |
| 0e9e827 ModelSource port | accept, no defect | — |
| d2efdd6 OPS_MODELS_URL+KEY integration | accept, no defect | — |
| c3f951b refusal reaches caller | accept, no defect | — |
| 081e5dd re-run replays, no key stays direct | accept, no defect | — |
| ba2828b GET /v1/model-aliases | accept, no defect | — |
| c1f4a85 settle before [DONE] | accept, no defect | — |
| 9e71c14 uc-028 use case | accept, no defect | — |
| c1d1095 E13 experiment | accept, no defect | — |
| f23d68f errorCode persists on reload | accept, no defect | — |
| 2c89ed7 E13 real baseline | accept, no defect | — |
| fc3f960 runtime.md + overview docs | accept, no defect | — |
| Probe 1: disconnect before [DONE] | shielded settle works, row+spend exist, pool healthy | — |
| Probe 2: rate limit one denied row | max_retries=0 holds, exactly 1 denied row | — |

verdict: approve
