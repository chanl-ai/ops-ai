# Models-service hop: what routing turns through models-service adds

Status: E13, holds, 2026-10-11. Script: `services/agents-service/experiments/e13_models_service_hop.py` (scripted
provider, no tokens); `make experiment E=13 APPROVED_REAL_CALLS=13 ARGS="--only real --real-approved"` made the 10
owner-approved real calls, about $0.01. Card: c-009.

## Verdict

Sending a turn through models-service (one HTTP round trip, key lookup, rate count, a log row and the spend update)
adds 7 ms at p50 and 12 ms at p95 at concurrency 1, and 16 / 35 ms at concurrency 5. Against E8's real-model turn
(1,074 ms model, 52 ms overhead at p50) that is under 1% of the turn, inside the 150 ms overhead budget. With the real
model, five turns a side, the difference is lost in model variance: through models-service was 266 ms slower at p50
and 147 ms faster on the mean.

## Numbers

Kernel turns with an instant scripted model, models-service on a real local server (ms, p50 / p95 / p99):

| Group | Turns | Total | Mean |
|---|---|---|---|
| In process, concurrency 1 | 50 | 3 / 6 / 10 | 4 |
| Through models-service, concurrency 1 | 50 | 11 / 18 / 50 | 12 |
| Hop, concurrency 1 | | 7 / 12 / - | |
| In process, concurrency 5 | 50 | 7 / 8 / 8 | 7 |
| Through models-service, concurrency 5 | 50 | 23 / 43 / 44 | 25 |
| Hop, concurrency 5 | | 16 / 35 / - | |

Real model, gpt-5.5, plain turn, direct and through models-service interleaved, 10 calls (ms, p50 / p95):

| Group | Turns | Total | Mean |
|---|---|---|---|
| Direct | 5 | 1,703 / 2,909 | 1,945 |
| Through models-service | 5 | 1,969 / 2,121 | 1,798 |

Tokens per call through models-service: 93 in, 65 to 88 out. Cost about $0.01 for the 10 calls, estimated from E8's
spend per call; models-service logged 0 because the experiment's alias has no price set.

## Gotchas

| Gotcha | Handling |
|---|---|
| A streamed reply's log row was written after `[DONE]` | The client disconnects on `[DONE]` and Starlette cancels the write; settled before `[DONE]` (c1f4a85) |
| The scripted stream sent no usage chunk | Callers metered 0 tokens; it now ends with OpenAI's usage chunk (c1f4a85) |
| Concurrency 5 doubles the hop | Five turns share one models-service process and one database pool; p95 is where it shows |
| Five real turns a side cannot resolve a 7 ms hop | Measure the hop on the scripted provider; use real calls only to confirm nothing breaks |
| The experiment's alias had no price | Price aliases before any spend report reads models-service's cost |

## What it feeds

| Item | Feeds |
|---|---|
| The scripted hop number | c-009 latency baseline |
| The concurrency-5 p95 | models-service pool size and a reservation per call (the cap is checked before the call) |
