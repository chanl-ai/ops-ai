# Cost and budgets: usage per model call, a thread that pauses at its cap

Status: E12, holds, 2026-10-11. Scripted model only, no real calls. Tests:
`services/agents-service/tests/api/test_budgets.py`. Script: `services/agents-service/experiments/e12_cost_and_budgets.py`.
Library: `packages/ops_metering` (usage, prices, cost, totals, budget checks; no I/O).

## Verdict

Every model call a graph makes (the kernel turn and the four workflow calls) writes one usage row, and a thread with a
budget pauses for a person when it is spent, through the same interrupt a human step uses. Cost is summed by the
database from those rows; no caller adds anything up. The per-key ledger belongs to models-service and sits behind a
port that admits every key today.

## What holds

| Failure mode | Result |
|---|---|
| A thread runs past its cap in the middle of the redraft loop | holds: paused before the next call, `cost.calls` equals the cap |
| A paused thread does not say why | holds: interrupt `budget_exhausted` with limit, spent and cap; `budget` and `cost` in GET state |
| Raising the cap does not continue the case | holds: approved with `budget` resumes and reaches the review |
| A rejected budget pause keeps running | holds: the run ends in error, no further call |
| A key at its cap still opens a thread | holds: 429 `key_budget_exhausted` with the reason; no thread created |
| A scripted model is charged, or a priced alias is not | holds: zero cost unpriced; priced cost matches tokens × table price |
| A crashed attempt's usage is lost when its node re-runs | holds: the failed call and its re-run are both counted, per run in GET runs |

Each test fails when its fix is removed (guard, record-on-failure, key check). Usage rows are written as each call
returns, outside the checkpoint and unfenced, so spend from a crashed or superseded run is still counted.

## Numbers

5 threads × 400 calls, compose PostgreSQL, unloaded; check is the budget row plus a sum over the thread's rows:

| Rows already in the thread | Check p50 / p95 ms | Record p50 / p95 ms |
|---|---|---|
| 0–99 | 2.03 / 3.48 | 1.10 / 1.95 |
| 300–399 | 2.05 / 2.57 | 1.09 / 1.48 |
| All | 2.05 / 3.70 | 1.10 / 2.04 |

Per model call 3.2 ms p50, 5.5 ms p95, against about 1 s for the call itself (E8). 400 calls of 600 + 50 tokens at
1.25 / 10 per million cost 0.500000, matching the arithmetic.

## Gotchas

| Gotcha | Handling |
|---|---|
| The cap is checked before a call, so the crossing call completes | Spend can pass a cap by one call per concurrent task |
| Fan-out tasks check the budget at once and can all pass | Overshoot up to the fan-out width (4); acceptable for a soft cap |
| LangGraph restarts a node on resume | Calls the node made before the pause run again and are counted again |
| An approval with no new cap pauses again at once | The person must send a higher `budget` |
| Usage of a failed provider call is unknown | Counted as one call with zero tokens |
| Chat routes (`/chat/*`) are not metered | Only graph runs on threads; chat moves to the graph path later |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Per-key ledger in models-service behind `KeyAdmission` | Key budgets and chargeback |
| Meter the chat routes, or move chat onto the graph path | One ledger for all spend |
| Console: budget and cost on the case and run pages | Operators see spend |
