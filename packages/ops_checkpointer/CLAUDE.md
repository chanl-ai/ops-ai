# ops_checkpointer: working rules

Status: current.

A LangGraph checkpointer on SQLAlchemy Core, with the same statements on PostgreSQL and SQL Server, replacing
`langgraph-checkpoint-postgres` and its LGPL `psycopg`. Each checkpoint is stored whole as one serde blob, every
statement runs in the caller's tenant and team isolation context, and writes are fenced by the thread lease's
generation. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Name | What it is |
|---|---|
| `CheckpointSaver` | The `BaseCheckpointSaver` implementation (`src/ops_checkpointer/saver.py:87`) |
| `open_saver(database_url, ...)` | Opens a saver on a database URL |
| `LeaseSupersededError` | A write whose lease generation is below the thread's fence, or a write with no generation on a fenced thread |
| `NoTeamError` | A write with no team in the isolation context; every row is in exactly one team |
| `ThreadJournal` | What prune asks before deleting history: the thread is closed and its run is journalled |
| `RLS_ROLE` | `ops_runtime_tenant`, the role a saver switches to per transaction so row-level security applies to a superuser connection |
| `tables` | The three tables as SQLAlchemy metadata, the one source of their schema |

## Contract with callers

- The saver takes tenant and team from `ops_store.isolation`, so one compiled graph serves every tenant and team. A
  caller enters the isolation context before running a graph; it never passes a tenant to the saver by hand.
- Upserts and row locks come from `ops_store.dialect`; this module and `tables` are the only files here allowed to
  import SQLAlchemy (`.importlinter`).
- The migrations live in agents-service's chain (0004, 0008, 0071, 0090) and are held equal to `tables` by
  `deploy/database/tests/test_model_parity.py`. A column change edits `tables.py` and adds an agents-service migration
  in the same commit.

Depends on `ops_store`. Depended on by `ops_engine` and agents-service.

## Run and test

No tests in this folder; they live in agents-service and need PostgreSQL, which `make test` provides.

| Task | Command |
|---|---|
| The checkpointer suite (conformance, fencing, prune, RLS, team; 11 tests) | `make test PKG=services/agents-service T=tests/checkpointer` |
| Schema parity with the migrations | `make test PKG=deploy/database T=tests/test_model_parity.py` (plain `uv run pytest` skips it without `OPS_TEST_DATABASE_URL`) |
| Lint, format, types | `uv run ruff check packages/ops_checkpointer`, `uv run ruff format --check packages/ops_checkpointer`, `uv run pyright packages/ops_checkpointer` |

## Reference docs

- [docs/architecture/decisions/fencing-and-timers.md](../../docs/architecture/decisions/fencing-and-timers.md): leases and fencing
- [docs/architecture/decisions/durable-execution-runtime.md](../../docs/architecture/decisions/durable-execution-runtime.md)
- [docs/architecture/decisions/database-support.md](../../docs/architecture/decisions/database-support.md)
