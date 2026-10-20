# Agent completions through models-service

Status: research note for a card, nothing built. Date: 2026-10-11. Reads with
[ADR-0008](../architecture/decisions/ai-gateway.md), [models-service](../services/models-service/overview.md) and
[E8, chat turn latency](../services/agents-service/experiments/chat-turn-latency.md).

Goal: the alias an agent carries is the model its turns run on, and agents-service holds no provider keys. Today the
alias is checked at publish and reported by the test turn, but every turn runs on the runtime's one model, built at
boot from a provider key in agents-service's environment.

## What exists

| Piece | State | Where |
|---|---|---|
| Model wrapper | `LedgerModel` wraps one Pydantic AI model; inside a graph run it records each call (alias, tokens, latency, thread, run, step, task, request hash, response) and replays a crashed node's re-run from the record. Chat turns pass through unrecorded | `api/model_ledger.py` |
| Kernel | Builds the turn's `Agent` with `ports.model`: one model for every agent | `ops_agent_kernel/kernel.py:216` |
| Direct provider | `build_model(settings)`: OpenAI, or Anthropic for `claude-*`, keyed from the environment | `ops_agent_kernel/models.py` |
| models-service completions | `POST /v1/models/completions`: model key as Bearer, alias in `model`, thread, run and step as headers. Checks key status, rate limit (calls in the last minute), alias, sensitivity; meters spend; writes the call log. Non-streaming; forwards text only | `ops_models/app.py:368` |
| Providers | `scripted` (echo, word-count tokens) and `openai-compatible`; Anthropic registrable but not served | `ops_models/providers.py` |
| OpenAPI | agents-service has `openapi.json`; models-service has none | |

## Design

A completions port in the kernel, `ModelSource.model_for(alias) -> Model`, with two adapters chosen by `OPS_MODELS_URL`:

| Adapter | When | What it does |
|---|---|---|
| Direct | `OPS_MODELS_URL` unset | Today's `build_model`, for the runtime alias only; an agent naming another alias is refused at publish already (only the runtime alias is known). Every existing use case stays on this path |
| models-service | `OPS_MODELS_URL` set | One `OpenAIChatModel` per alias, cached, pointed at models-service with agents-service's model key. Thread, run, step and request hash go as headers through `extra_headers` |

The kernel asks for `model_for(req.settings.model_alias)`; `LedgerModel` wraps the result and records the alias it
was given, not the runtime's.

## What has to change, and why

| Change | Why |
|---|---|
| models-service serves `stream: true` as SSE chunks | Turns use `run_stream_events`, which sends `stream: true`; a JSON answer fails in the OpenAI client |
| models-service forwards `tools` and returns `tool_calls` (both modes) | The provider parses `content` only, so a tool turn through models-service would silently lose its tool calls |
| An OpenAI-shaped path, `POST /v1/models/chat/completions`, beside the current one | Pydantic AI's provider appends `/chat/completions` to its base URL |
| `request_hash` column on the call log (migration 0002) | Ties a models-service row to the agents-service record and its replay key |
| OpenAI client with `max_retries=0` | The client retries 429 twice by default: one over-limit turn becomes three calls, and the 429 arrives late or not at all |
| `LedgerModel` records the per-call alias | It records `settings.model_alias`, so the record would say the runtime alias whatever ran |
| Turn errors map models-service refusals: 429 `rate_limited` and `key_budget_exhausted`, 403 `sensitivity_not_cleared`, 404 `alias_not_found`, 502 `provider_error` | The kernel turns any model exception into a generic failed turn |

## uc-028

| Check | Evidence |
|---|---|
| An agent published on alias X runs on X | Test turn reports X; models-service's call log has a row with alias X, its version and provider model, and the turn's thread |
| In a graph run, the record says X | `model_call_records.model_alias` is X, and its request hash matches the call-log row's |
| An unknown alias is refused | Publish request answers 422 `unknown_model_alias` (already in uc-018; uc-028 repeats it on this path) |
| A key over its limit answers 429 through the whole path | Key issued with `rateLimitPerMinute: 1`; the second test turn answers 429 `rate_limited`; the call log has one `ok` and one `denied` row, no third |

Scripted provider on the models-service side, so no real calls; models-service runs from the use-case harness's
`models()`.

## Decisions for the card

| Question | Recommendation |
|---|---|
| Which key agents-service presents | One key per environment for agents-service (`agents:<env>`) now; per-workflow keys from spec 03 when publish issues them. The call log already carries thread and run, so spend per workflow is derivable meanwhile |
| A rate limit inside a streamed chat turn, which has already answered 200 | The test turn (JSON) answers HTTP 429; a streamed turn ends with a failed event carrying `rate_limited`. Admission (`/v1/models/admit`) at thread open stays as is |
| Two budgets: agents-service's per-run cap (E12) and the key's budget | Keep both; whichever refuses first ends the turn, with its own code |
| Anthropic aliases | Direct mode keeps the `claude-` path; through models-service they wait for its Anthropic provider |

## Latency baseline

At most 10 real calls: the E8 plain turn, five direct and five through models-service on one openai-compatible
alias, about $0.01 at E8's 588 tokens in and 46 out. E8's plain p50 is 1,074 ms model and 52 ms overhead. The added
hop is one HTTP round trip and three statements in models-service (key lookup, rate count, log insert plus spend
update); expected under 20 ms at p50, and the volume measurement runs on the scripted provider.

## Slices

| # | Slice | Proof |
|---|---|---|
| 1 | models-service: OpenAI path, SSE streaming, tool passthrough, `request_hash` column, `openapi.json` | Tests on the scripted provider and a MockTransport provider |
| 2 | Kernel port, both adapters, per-call alias in `LedgerModel`, `max_retries=0` | Unit tests; uc-020 on the direct path unchanged |
| 3 | Refusal mapping in the turn routes | Tests per refusal code |
| 4 | uc-028, both `openapi.json` files, docs | uc-028 green; uc-018, uc-019, uc-020 still green |
| 5 | Latency baseline, cost in the commit | At most 10 real calls |
