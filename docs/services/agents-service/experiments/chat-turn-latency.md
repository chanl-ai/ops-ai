# Chat turn latency: model time against agents-service overhead

Status: E8, confirmed, cut short, 2026-10-10. The live batch stopped at 118 turns under the maintainers' cap of 10 real model
calls per experiment. Script: `services/agents-service/experiments/e8_latency.py` (fake model, no tokens); `--only timed`
makes 9 real calls, and the live part needs `--live-approved`. No tests.

## Verdict

The model is 95 to 96% of a chat turn, and agents-service adds 52 to 89 ms at p50 with the real model, under the
150 ms budget for context assembly, retrieval, persistence and SSE.

## What holds

| Failure mode | Result |
|---|---|
| Overhead (total minus model) exceeds 150 ms | holds (at most 89 ms with the real model, 73 ms p95 with the fake one) |
| Concurrency 5 pushes overhead past budget | holds (fake model: 26 to 53 ms at p50) |
| First byte and first text measured | not run (lost when the live batch stopped) |
| Workflow latency on a real server | not run (measured in process on fake ports) |

The real model costs more overhead than the fake one (52 against 26 ms, plain p50) because it streams many small
deltas, each an SSE event through Pydantic AI's stream handling.

## Numbers

Real model, 8 turns with the model call timed (ms, p50 / p95 / p99):

| Group | Total | Model | Overhead |
|---|---|---|---|
| Plain (n=5, first cold) | 1121 / 1425 / 1479 | 1074 / 1360 / 1409 | 52 / 69 / 71 |
| Read tool (n=1, 2 model calls) | 2201 | 2113 | 89 |
| Write tool to its approval (n=2) | 1588 / 1756 / 1771 | 1525 / 1682 / 1696 | 63 / 74 / 75 |

Fake model in process, scratch PostgreSQL (total ms, p50 / p95 / p99):

| Group | Total |
|---|---|
| Plain, concurrency 1 / 5 (n=50 each) | 26 / 45 / 51, 53 / 70 / 74 |
| Read tool (n=50) | 30 / 55 / 65 |
| Write tool to its approval (n=50) | 34 / 45 / 73 |
| Simple workflow through the four calls (n=20) | 34 / 40 / 49 |

Per turn: plain 588 tokens in, 46 out; read 1,314 in, 93 out. Total spend about 144 real calls, about $0.18.

## Gotchas

| Gotcha | Handling |
|---|---|
| httpx's in-process transport buffers the stream, so first byte equals total | Measure first byte and first text against a real server |
| Live concurrency 5 looked faster than 1 (p95 1,271 vs 1,744 ms) | Model variance swamps overhead at 50 turns; compare overhead on the fake model |
| Cold first turn is about 0.5 s slower (connection set-up, first imports) | A fresh image also downloads tiktoken's encoding on turn one; vendor it |
| :8700 does not record token usage | Token counts come from the timed part's per-turn means (E12 records usage) |
| The live batch made about 135 real calls, past the cap | Fake port for volume, at most 10 real calls for the baseline |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| First-byte and first-text times against a real server | Perceived chat latency |
| Vendor tiktoken's encoding into the image | Cold first turn |
