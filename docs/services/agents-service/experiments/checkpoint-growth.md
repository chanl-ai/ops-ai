# Checkpoint growth: storage and write latency per thread

Status: E4, confirmed, 2026-10-10. Dispute workflow on the asyncpg checkpointer with a stubbed model; no model calls.
Script: `services/agents-service/experiments/e4_checkpoint_growth.py` (about a minute, scratch database `ops_e4`).
No new tests; the prune guard (no prune while open, leased or without a journal row) is covered by E0's and E2's tests.

## Verdict

Checkpoint storage grows linearly with steps × state size, and write latency grows linearly with checkpoint size,
passing 50 ms near 2 MB per checkpoint unloaded and sooner under load. A long case stays bounded with references in
state, no payload copies between state keys, pruning of closed threads, and maintenance that returns disk space.

## What holds

| Failure mode | Result |
|---|---|
| Storage grows faster than steps × state size (9 checkpoints, 81 writes per thread) | holds (linear) |
| Checkpoint size grows with attachments when state holds references | holds (largest stays 11 KB) |
| Prune leaves write rows behind | holds (keep_latest removed 89% of checkpoint rows and every write row) |
| Prune returns disk space | fails (only VACUUM FULL does) |
| Per-version channel storage cuts payload-heavy state about 9× | not run (estimate) |

The saver stores each checkpoint as one blob of every channel, so every step rewrites the whole state: about 90 KB
per step and 738 KB per thread against about 80 KB of attachment text.

## Numbers

50 cases per scenario, 20 attachments of non-repeating text. Raw is `octet_length`, stored is after TOAST; write
latency is p95 of `aput`, serialisation excluded.

| Scenario | KB / thread raw | KB / thread stored | Largest checkpoint KB | p95 write ms |
|---|---|---|---|---|
| Payloads, 20 × 2 KB | 869 | 411 | 124 | 8.96 |
| References, 20 ids | 72 | 30 | 11 | 5.28 |
| Payloads, 20 cases at once | 869 | 411 | 124 | 67.02 |
| 10 / 25 / 50 KB × 20 | 4,069 / 10,069 / 20,069 | 1,916 / 4,716 / 9,391 | 604 / 1,504 / 3,004 | 17.56 / 40.84 / 65.17 |
| 100 / 200 KB × 20 | 40,070 / 80,070 | 18,740 / 37,436 | 6,004 / 12,004 | 122.33 / 245.30 |
| 400 / 800 KB × 20 | 160,070 / 320,070 | 74,813 / 149,572 | 24,004 / 48,004 | 491.44 / 987.96 |

100 threads: prune cut rows from 900 + 8,100 to 100 + 0 in 732 ms but table size stayed 19.63 MB; VACUUM FULL brought
it to 2.43 MB. Load, 100 cases 20 at a time: 2.5 s, PostgreSQL 116% of one core, 3,056 commits/s, WAL 17.1 MB/s.

## Gotchas

| Gotcha | Handling |
|---|---|
| State holds each attachment twice (`email.attachments` and classify's `attachments`) | Drop the copy; halves storage before references |
| Send fan-out writes payloads into `__pregel_tasks` | References in the Send packets |
| Repeated test text compresses about 25× and hides size; msgpack vs JSON differs by 1% | Measure with realistic text; count copies, not serialisers |
| Prune frees rows, not disk; VACUUM returns neither TOAST pages nor index space | VACUUM FULL in a window, time partitions, scheduled REINDEX CONCURRENTLY |
| keep_latest keeps the heaviest checkpoint (about 52 KB per finished thread) | `delete` strategy once the journal holds the record |
| 20 concurrent cases take p95 from 9 to 67 ms at the same size | Concurrency dominates under load; size the database for it |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Attachments as `file:<id>` references in state; drop the duplicate key | Bounded long cases |
| Saver that stores channel values per version | Payload-heavy state, about 9× less (estimated) |
| REINDEX schedule, time partitioning, `delete` for closed threads | Checkpoint table maintenance |
