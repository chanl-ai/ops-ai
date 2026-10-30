# Checkpoints per channel version against whole-state checkpoints

Status: measured, not adopted, 2026-10-11. Run with E4's dispute workflow and stubbed models on a scratch database
(`ops_blobsize`), no model calls. Its script and the variant saver were built on the asyncpg checkpointer and were
removed when the checkpointer moved to SQLAlchemy Core; `git show 8d793955:services/agents-service/experiments/`
lists them.

## Verdict

Storing each channel once per version, as LangGraph's own PostgreSQL saver does, cuts payload-heavy threads 2.5 to
2.8 times, not the 9 times E4 estimated, and only 14% for state that holds file references, which is how our graphs
keep attachments. Writes cost the same and reads cost more, because a read joins the blobs back. For the state we
keep, the saving does not pay for a second table, a second read query and blob-aware prune, copy and delete.

## Numbers

Bytes per thread count checkpoint rows, pending writes and the variant's blobs; stored is after TOAST. The variant
passes LangGraph's conformance suite: 81 passed, 0 failed.

| Scenario | Saver | KB / thread raw | KB / thread stored | p95 write ms | p95 read ms |
|---|---|---|---|---|---|
| Payloads, 20 x 2 KB | whole state | 869 | 410 | 8.48 | 22.54 |
| Payloads, 20 x 2 KB | per version | 314 | 161 | 8.32 | 27.51 |
| References, 20 ids | whole state | 72 | 29 | 6.03 | 24.90 |
| References, 20 ids | per version | 35 | 25 | 7.63 | 27.88 |
| Payloads, 20 x 50 KB | whole state | 20,069 | 9,393 | 69.12 | 28.85 |
| Payloads, 20 x 50 KB | per version | 7,034 | 3,306 | 55.37 | 34.01 |

Write p95 stayed within run-to-run noise over three one-transaction runs; reads were 11 to 55% slower in both runs
that measured them.

## Gotchas

| Gotcha | Detail |
|---|---|
| Not 9x | Pending writes are untouched by the variant and carry payloads too (Send packets, task outputs); the estimate counted checkpoints only |
| Two transactions doubled the cost | The first build wrote blobs and checkpoint in separate transactions and its p95 write was 60% worse on references; one transaction made writes level |
| Reads need the blobs | Every get and every listed checkpoint adds a query; a join in the base query would trim it, not remove it |
| Blobs outlive deleted runs | `delete_for_runs` cannot drop blobs another checkpoint of the thread may name; they wait for prune or thread delete |
| Prune is application work | Unreferenced blobs are found by decoding the kept checkpoints' channel versions |

## What it feeds

| Into | What |
|---|---|
| checkpoint-growth.md | Its "about 9x" per-version estimate is 2.5 to 2.8x for payloads, 14% for references |
| Saver choice | Revisit only for a graph that must keep payloads in state; references remain the rule |
