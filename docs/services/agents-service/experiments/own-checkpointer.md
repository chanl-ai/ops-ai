# Own checkpointer on asyncpg, with no LGPL dependency

Status: E0, confirmed, 2026-10-10. Replaces LangGraph's psycopg saver with `AsyncpgSaver` in `packages/ops_checkpointer`.
Tests: `services/agents-service/tests/checkpointer/` (conformance, RLS, prune). End to end:
`services/agents-service/scripts/prove-graphs.py` (calls the model, needs `OPENAI_API_KEY`).

## Verdict

The asyncpg saver passes all 81 LangGraph conformance cases including the extended capabilities, the graphs run and
resume after SIGKILL on it, and psycopg (LGPL-3.0) is out of the lock.

## What holds

| Failure mode | Result |
|---|---|
| Saver misses a LangGraph capability (`langgraph-checkpoint-conformance` 0.0.2) | holds: FULL 8/8, 81 cases |
| Run killed with SIGKILL at the human step loses its place | holds: resumed on a second process at `human`, review id unchanged |
| Tenant B reads tenant A's thread (`aget_tuple`, `alist`, raw `SELECT` with no tenant clause) | holds: `None`, `[]`, count 0 |
| Tenant A inserts a row for tenant B | holds: `InsufficientPrivilegeError` |
| Prune drops state of a running or interrupted thread | holds: not pruned; an idle thread with a finished run keeps one checkpoint and its pending write |

Tables `ops_checkpoints` and `ops_checkpoint_writes` (migration `0004_checkpointer`) force row-level security on
`tenant_id = current_setting('app.tenant_id', true)`. The saver is bound to one tenant and team when built (`for_scope`
for another) and never reads them from run config, so whoever builds a config cannot choose the tenant.

## Numbers

Compose PostgreSQL, fresh tenant per suite; end-to-end run under tenant `local`:

| Measure | Value |
|---|---|
| Conformance cases passed | 81 of 81 |
| End-to-end writes | 74 checkpoints across 9 threads, 205 writes |
| Packages in the lock | 83 before, 79 after |
| LGPL or GPL licences | 3 before, 0 after (`docs/architecture/dependencies.md`, from `make sbom`) |

## Gotchas

| Gotcha | Handling |
|---|---|
| The conformance suite has to be able to fail | Checked: an `alist` that ignores `before` scored 14 passed, 2 failed |
| Superusers bypass RLS, and the compose user is one | Saver runs `SET LOCAL ROLE ops_runtime_tenant`; production should connect as a non-superuser that owns no tables |
| Replayed task writes | Regular writes insert-or-ignore (first copy kept); errors, interrupts and resumes upsert (latest kept) |
| Whole channel values in every checkpoint repeat unchanged channels | `prune_thread` bounds closed threads; open threads grow until a per-channel blob table exists |
| Prune keeps only the latest checkpoint | Breaks a graph using LangGraph's beta `DeltaChannel`; none do. Such a graph needs ancestor-preserving prune |
| Filtered `alist` applies `limit` after an exact equality check (`jsonb @>` is looser) | Fine at prototype volume; a scan on large threads |
| Conformance package is 0.0.2 | Re-run on every `langgraph-checkpoint` upgrade |
| Old psycopg tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`) | Threads there do not move over; drop once nothing reads them |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Identity carries the tenant; router picks a saver per scope (today tenant and team `local`) | Real multi-tenancy |
| Per-channel blob table | Storage growth on open threads |
| Non-superuser connection role in production | RLS without the role switch |
| Drop old psycopg tables | Database cleanup |
