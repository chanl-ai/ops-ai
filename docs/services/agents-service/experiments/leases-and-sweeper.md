# Thread leases and a recovery sweeper

Status: E2, holds, 2026-10-10. Two agents-service processes on shared PostgreSQL, lease TTL 6 s, 1 s sweep.
Tests: `services/agents-service/tests/api/test_leases.py`. Script:
`services/agents-service/experiments/e2_leases_and_sweeper.py` (calls the model, needs `OPENAI_API_KEY`).

## Verdict

Two processes cannot run one thread at the same time, and a process killed mid-node leaves no stuck thread: the other
process recovers it from the last checkpoint. The killed node runs again, so its model calls are paid twice and any
side effect inside it repeats unless the receiver deduplicates.

## What holds

| Failure mode | Result |
|---|---|
| Two processes start one thread at the same instant | holds: one runs, the other gets 409 `run_active` naming owner and run, age 0.0 s |
| A stale lease from a dead owner blocks the thread | holds: reclaimed by the sweeper |
| A long node loses its lease mid-run | holds: heartbeat keeps it leased |
| Process killed mid-node leaves the thread stuck | holds: recovered, reached its review, `send_reply` ran once |
| Stale owner writes after a takeover | fails: not fenced here; see `fencing.md` |

The lease (`thread_leases`, migration `0005_leases`) is taken by one `INSERT … ON CONFLICT DO UPDATE … WHERE
expires_at < now RETURNING`, renewed every TTL/3, deleted at run end. The sweeper takes expired leases with the same
statement, marks the dead run `crashed`, and runs the graph with no input to continue from the last checkpoint.

## Numbers

Two runs, SIGKILL on process A with 3 extract calls in flight:

| Measure | Value |
|---|---|
| Kill to recovery start | 5.46 s and 5.40 s (bound: 4 to 7 s at these settings) |
| Kill to review reached | 12.17 s and 12.91 s, about 7 s of it the recovery's own model calls |
| Extra model calls per crash | 3: every extract in flight; finished `classify` not repeated |
| `send_reply` | ran once |

## Gotchas

| Gotcha | Handling |
|---|---|
| LangGraph saves between steps, so a killed node re-runs from its start and the repeat may differ | Accepted; finished fan-out tasks keep their writes (not exercised here) |
| `send_reply` dedup ledger lives in process memory, so a crash mid-send would send twice | Dedup where the call lands: the gateway, keyed by `runId:actionId` (E3) |
| A lost lease cannot stop a node already running; its write can land after takeover | Fencing token on writes (E2b, `fencing.md`) |
| Shorter TTL recovers faster but risks a live lease expiring during a pause | Choose per deployment; clock skew across hosts must stay well under the TTL |
| Crashed run's journal row is empty (`owner port ?`, no nodes) | Write owner at start and events as they happen (done in E2b) |
| Recovery runs inside the sweep loop, one thread at a time | Production: one task per recovery, with a cap |
| Crash before the first checkpoint has no state | Sweeper restarts from `graph_runs.input`; implemented, not exercised |
| Shared database carried another lane's `0006_gateway`, failing Alembic on checkouts without it | Verify against a fresh database |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Fencing of stale-owner writes | E2b |
| Deduplication in the gateway | E3 |
| Per-recovery tasks with a cap | Production sweeper |
