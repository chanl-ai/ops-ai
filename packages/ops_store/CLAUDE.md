# ops_store: working rules

Status: current.

The store seam. Every service reaches its database through this package: it opens the database, carries the tenant
and team into every transaction, holds the few statements that differ between PostgreSQL and SQL Server, and proves
the guarantees a repository relies on with conformance suites. It holds no service's tables. Package rules and test
commands shared by every package: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `guarantees` | `Guarantee` (CAS, transaction, lock, clock, RLS), `Repository` (declares the guarantees it needs), `Backend`, `unmet` |
| `ports` | `LeasePort`, `TimerClaimPort`, `AuditPort`: the repository protocols the conformance suites test |
| `conformance` | `lease_suite`, `timer_claim_suite`, `audit_suite`, `isolation_suite`, run against every backend from `backends` |
| `backends` | The registered backends; PostgreSQL is the only one, on a `<db>_conformance` database next to the test database |
| `database` | `open_database(url)`: the handle code outside a store holds; tests pooled connections and retries a stalled connect |
| `isolation` | The one isolation context: `enter_caller`, `isolated_tx`, `tenant_wide`, `system_tx`, `NoTenantError` |
| `team_scope` | `team_visible` and `any_team`: the where-clause every read of a team-owned table carries |
| `schema` | `TENANT_SCOPED` and the team-owned markers on tables; `differences` and `unowned` compare a migrated database with the metadata |
| `schema_version` | `require_current_schema`: a service refuses to start when its chain's head is not recorded |
| `dialect` | `locked`, `claim`, `upsert`, `insert_ignore`, `lock_key`, `db_now`, `db_epoch`, `db_after`, `system_tx`, `full_text` |
| `search` | `contains` and `like_pattern`: portable, escaped, case-insensitive text search |
| `outbox` | `outbox_table`, `add`, `Relay`: an event written in the same transaction as its change, delivered at least once |
| `background` | `PROCESSES`, `run`, `Beat`, heartbeats (`MemoryHeartbeats`, `DbHeartbeats`) behind `/health/background` |
| `reference` | `SqlAuditLog`: a reference audit log for a service that has none, and the audit suite's own check |

## Contract with callers

- Every read and write of an isolated table runs inside `isolation.isolated_tx`; with no context it raises
  `NoTenantError` before a connection opens (`src/ops_store/isolation.py:1`). `ops_identity` enters the context once per
  request from the verified caller, never from a body, header or path.
- Widening past one team needs a reason that is a named constant of the calling service: `tenant_wide` for every team
  of one tenant, `system_tx` past the tenant. `tests/test_isolation_sites.py` lists every call site by reason, so a new
  one fails that test until it is listed.
- A table marked `TENANT_SCOPED` is isolated by the database itself (forced row-level security on PostgreSQL, a
  security policy on SQL Server); `schema.differences` reports a marked table the database does not isolate, or the
  reverse.
- Code outside this package uses `dialect` for locks, claims, upserts and the database clock. `with_for_update()` alone
  renders nothing on SQL Server (`src/ops_store/dialect.py:1`); `scripts/check_portable_store.py --strict` refuses it
  elsewhere.
- A new repository that relies on a guarantee adds or reuses a conformance suite and runs it against `backends(...)`.

Depended on by `ops_checkpointer`, `ops_engine`, `ops_identity` and every Python service except runner-service.

## Run and test

| Task | Command |
|---|---|
| The suite (needs PostgreSQL; `make test` provides a throwaway database) | `make test PKG=packages/ops_store` (66 tests, about 20 s) |
| One file | `make test PKG=packages/ops_store T=tests/test_isolation_sites.py` |
| Lint, format, types | `uv run ruff check packages/ops_store`, `uv run ruff format --check packages/ops_store`, `uv run pyright packages/ops_store` |
| Store inventory in `docs/architecture/data.md` | `uv run python scripts/store_inventory.py --check` (rewrite without `--check`) |
| Portability | `uv run python scripts/check_portable_store.py --strict` |

`tests/test_database.py` and `tests/test_outbox.py` skip their PostgreSQL-only cases on SQLite. A change here runs
every dependant's suite under `make test` with no `PKG`.

## Gotchas

| Gotcha | Rule |
|---|---|
| `backends()` names only PostgreSQL, so the conformance suites never run on SQL Server here | SQL Server DDL and model parity are checked in `deploy/database/tests` (`make test PKG=deploy/database`, the `pool-deploy` job of `make verify`; at this working tree `tests/test_mssql_ddl.py` and `tests/test_offline.py` fail on agents and tools DDL that differs from the reviewed golden files) |
| The conformance database is `<test database>_conformance`, created on first use | Two sessions with different test databases never migrate each other's |
| Importing `ops_store` installs the connect retry on every SQLAlchemy engine in the process (`src/ops_store/__init__.py:11`) | Engines made in scripts and tests get it without passing anything |

## Reference docs

- [docs/architecture/data.md](../../docs/architecture/data.md): store inventory and data rules
- [docs/architecture/decisions/database-support.md](../../docs/architecture/decisions/database-support.md): PostgreSQL and SQL Server
- [docs/architecture/identity-and-tenancy.md](../../docs/architecture/identity-and-tenancy.md): tenant and team isolation
- [docs/architecture/decisions/fencing-and-timers.md](../../docs/architecture/decisions/fencing-and-timers.md): leases and the database clock
