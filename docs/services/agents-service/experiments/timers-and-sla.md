# Timers and SLA: durable timers for human steps

Status: E5 and E5b (ADR-0016), confirmed, 2026-10-10. Timers run in agents-service's worker; hitl-service will record
the timeout outcome and resolve groups to people. Tests: `services/agents-service/tests/timers/` (PostgreSQL, fake
model). Script: `services/agents-service/experiments/e5_timers_and_sla.py` (no model step).

## Verdict

A `timers` table and a poller give a `human` step durable warn, breach and max-wait timers, and a timeout resumes the
thread under its lease into exactly one outcome set by the step: reassign, escalate or reject. `fire(thread, timer)`
called in-process by the poller is the only fire path (the HTTP route was removed in c-168), idempotent on the timer id.

## What holds

| Failure mode | Result |
|---|---|
| A breach does not warn first or escalate; a decided step's timer fires | holds |
| A reassigned review keeps the old clock; a customer reply does not move the deadline | holds |
| `onTimeout: reject` leaves the review open; an escalated review waits forever (max wait rejects) | holds |
| Two pollers, the same timer id twice, or concurrent fires resume more than once | holds |
| A timer resumes a thread that is mid-run | holds (waits for the lease) |
| A poller dies after taking a timer and the timer is lost | holds (fails on a build that writes `fired_at` at pick-up) |
| Anyone can fire a timer; a cancelled or early fire acts; a failing resume retries forever | holds (set aside after 3 claims) |
| E5b tests against a deliberately broken build | not run |

`fire` takes the thread's lease, then re-checks in one transaction that the timer is due, open, and that its interrupt
and round still wait. A claim (`claimed_generation`, `attempts`, migration `0009`) replaces a held row lock, and
`fired_at` is written fenced by the claiming generation when the step's `node_end` arrives.

## Numbers

Due-to-fired latency, 12 warnings due across 6 s, database clock; idle load over 20 s with no timer due:

| Poll interval | Min / median / max latency | Idle transactions in 20 s |
|---|---|---|
| 1 s | 0.12 / 0.46 / 0.83 s | 50 |
| 5 s | 0.52 / 3.08 / 5.00 s | 19 |
| Poller off, sweeper on | n/a | 14 |

An idle poll writes no rows and no WAL.

## Gotchas

| Gotcha | Handling |
|---|---|
| LangGraph gives every interrupt in one task the same id (seen in 1.2.14, undocumented) | Timers keyed by interrupt id and round |
| Releasing the lease from another connection while a fenced transaction is open deadlocks | Release only after the transaction closes |
| A `#` in a timer id truncated the fire route to a 404 | Round separator is `.r` |
| Schedulers deliver twice, early or late | Duplicate and early calls change nothing; due is judged by PostgreSQL `now()` |
| Timer racing a run; leases use process clocks, timers the database clock | Resume takes the lease; skew beyond the lease margin could still race |
| Timers need `now()` intervals and `SKIP LOCKED` | Off on SQLite; every timer test runs on PostgreSQL. Warnings are at most once |
| Service token is a shared secret | Adequate on one internal network; the poller is the only scheduler shipped |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| pg_cron or cloud scheduler behind the `TimerScheduler` port, with OIDC or mTLS | Scheduling without the poller |
| Run the E5b tests against a broken build | Proof of the claim and retry cap |
| Resolve groups to people and notify | hitl-service cases |
