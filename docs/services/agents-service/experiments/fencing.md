# Fencing a stale owner with lease generations

Status: E2b, holds, 2026-10-10. Design per ADR-0016 (fence the thread, not the worker); scratch databases `ops_e2b`, `ops_e4`.
Tests: `services/agents-service/tests/checkpointer/test_fencing.py`, `services/agents-service/tests/gateway/test_fencing.py`,
`services/agents-service/tests/api/test_leases.py`. Script: `services/agents-service/experiments/e2b_fencing.py`
(the proof calls the model; `--only cost` does not).

## Verdict

A paused owner, thawed after a takeover, writes nothing that stands: checkpoints, journal rows, thread status, timers
and tools-service writes each check the lease generation inside their own transaction. Cost is about 0.5 ms per
checkpoint write.

## What holds

| Failure mode | Result |
|---|---|
| Stale owner checkpoints after takeover | holds: `write generation 1 < fence 3` |
| Write with no generation on a fenced thread | holds: refused |
| Stale owner replays an approved send at tools-service | holds: 409 `lease superseded`, checked before the dedup lookup |
| Same process re-takes its thread; its paused run writes status or finish (ADR-0016 test 6) | holds: refused; late finish appended as `stale_owner_finished` |
| Stale owner's timer, SLA journal or poller fired-mark | holds: refused |
| Stale tool write reaching tools-service before the new owner's first tool write | fails: passes; identical input is deduplicated, a different input takes effect |
| Model calls, SSE events, side effects bypassing tools-service, tools-service reads | not fenced |

`thread_leases.generation` rises on every acquire or takeover and released leases keep their row, so it never resets
(migration `0008_lease_generation`, times from PostgreSQL `now()`). Each store keeps its own fence
(`ops_checkpoint_fences`, `gateway_fences`); the new owner raises the checkpoint fence before its first read.

## Numbers

Live proof: TTL 4 s, A frozen with SIGSTOP mid-extract, thawed after B finished. A made 1 extract call after the thaw;
`send_reply` effects: 1. Cost: E4's references scenario, 50 cases each way, alternating, 450 checkpoints per pass:

| Pass | Checkpoint p50 | Checkpoint p95 | Task writes p95 |
|---|---|---|---|
| Unfenced | 2.59 / 2.81 ms | 6.18 / 6.38 ms | 6.85 / 6.67 ms |
| Fenced | 3.08 / 3.50 ms | 6.64 / 7.01 ms | 7.80 / 7.65 ms |
| Fence cost | +0.59 ms | +0.55 ms | |

## Gotchas

| Gotcha | Handling |
|---|---|
| LangGraph default durability `async` writes a step's checkpoint while the next step runs, so a refusal does not stop it | Runs use `durability="sync"`; adds the checkpoint write (E4: 3–9 ms unloaded) to each step |
| The heartbeat usually notices first, before any write | Storage fences are the backstop; the proof makes A's late writes directly |
| Step 0's checkpoint is written before `classify`, so freeze points mislead | Proof waits for the third checkpoint |
| Fencing per worker would let a process's own paused run through | Fence per thread |
| tools-service learns a new generation only from the new owner's first tool write | Raise its fence at takeover (done in E2c, `fence-on-takeover.md`) |
| E0 binds the tenant at saver construction, while the service map passes it in run config | Settle in the service map's later steps |
| Shared database carries other lanes' migrations | Run the suite on a fresh database |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Fence or route node-local side effects through tools-service | Effects that bypass the gateway |
| Tenant from run config versus saver construction | Service map later steps |
