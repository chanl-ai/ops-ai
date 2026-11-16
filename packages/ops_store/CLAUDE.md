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
| `database` | `open_database(url)`: the handle code outside a store holds; tests pooled connections and retries a stalled connect. `reachable(db)`: /health's probe, False within `database_health_timeout_s`, an outage logged once |
| `isolation` | The one isolation context: `enter_caller`, `isolated_tx`, `tenant_wide`, `system_tx`, `install_wide`, `NoTenantError`; `request_transaction` (one transaction per request) and `attempt` (a savepoint) |
| `store` | `Store`: the base of every service's store class (`tx()`, `install_tx(reason)`, `system_tx(reason)` as its `system_role`, `attempt(conn)`, `owner_teams`) |
| `team_scope` | `team_visible` and `any_team`: the where-clause every read of a team-owned table carries |
| `schema` | `TENANT_SCOPED` and the team-owned markers on tables; `differences` and `unowned` compare a migrated database with the metadata |
| `schema_version` | `require_current_schema`: a service refuses to start when its chain's head is not recorded |
| `dialect` | `locked`, `claim`, `upsert`, `insert_ignore`, `lock_key`, `db_now`, `db_epoch`, `db_after`, `system_tx`, `full_text` |
| `listing` | `list_page`: a list's page, total and facet counts in SQL on the caller's transaction, from the kit's `ListQuery`; `LISTED` marks a column a list filters or sorts on |
| `search` | `contains` and `like_pattern`: portable, escaped, case-insensitive text search |
| `outbox` | `outbox_table`, `add`, `Relay`: an event written in the same transaction as its change, delivered at least once; `relay(routes=, targets=)` and `run_relay` are the one wiring (`tests/test_relay_sites.py`) |
| `background` | `PROCESSES`, `run`, `Beat`, heartbeats (`MemoryHeartbeats`, `DbHeartbeats`) behind `/health/background`; `retention`, `register` and `run_sweep` for an append-only table's sweep |
| `copies` | `copy_table`, `apply`, `resync`: a local copy of another service's records keyed by tenant, id and revision, written by its events (an older revision changes nothing, nor an event older than a delete's tombstone) and repaired by a registered resync of the owner's full list, asked with no transaction open (`Process.cycle`) |
| `testing` | `loop_reports_failure`: the test every background process has in its service (`tests/test_loop_health.py`) |
| `reference` | `SqlAuditLog`: a reference audit log for a service that has none, and the audit suite's own check |

## Contract with callers

- Every read and write of an isolated table runs inside `isolation.isolated_tx`; with no context it raises
  `NoTenantError` before a connection opens (`src/ops_store/isolation.py:1`). `ops_identity` enters the context once per
  request from the verified caller, never from a body, header or path.
- Widening past one team needs a reason that is a named constant of the calling service: `tenant_wide` for every team
  of one tenant, `system_tx` past the tenant. `tests/test_isolation_sites.py` lists every call site by reason, so a new
  one fails that test until it is listed.
- A table marked `system(...)` (no tenant column) is read and written through `Store.install_tx(REASON)`, which needs
  no caller: the context is `isolation.install_wide`, no tenant. Every statement on a connection in that scope is
  checked before it is sent: one naming a table not marked `system(...)`, or raw SQL (text, a literal column, SQL for
  the driver), raises `InstallScopeError` naming it, whatever the login and whether the table has a row policy, and
  `team_visible` raises there too. Inside a request it is the request's connection, its scope restored after. Its
  reason is listed in `tests/test_isolation_sites.py` like a widening's (`tests/test_install_scope.py`).
- Inside a request that took `ops_identity.fastapi.Tx`, every `isolated_tx` of the request's task joins one
  transaction; another task (a gather branch, a created task, a stream's generator) opens its own. A database error
  that is caught runs inside `Store.attempt(conn)`; one that leaves an `isolated_tx` block otherwise fails the request
  (`RequestTransactionFailed`). A store never calls `engine.begin()` or `engine.connect()`: `tests/isolation_sites/`
  lists, one file per service, the sites still to move and the caught errors with no savepoint, and a row may only fall.
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
| The suite (needs PostgreSQL; `make test` provides a throwaway database) | `make test PKG=packages/ops_store` (112 tests, about 25 s) |
| One file | `make test PKG=packages/ops_store T=tests/test_isolation_sites.py` |
| Lint, format, types | `uv run ruff check packages/ops_store`, `uv run ruff format --check packages/ops_store`, `uv run pyright packages/ops_store` |
| Store inventory in `docs/architecture/data.md` | `uv run python scripts/store_inventory.py --check` (rewrite without `--check`) |
| Portability | `uv run python scripts/check_portable_store.py --strict` |

`tests/test_database.py` and `tests/test_outbox.py` skip their PostgreSQL-only cases on SQLite. A change here runs
every dependant's suite under `make test` with no `PKG`.

### On SQL Server too

The tests that run on both databases (`tests/test_listing.py`, `packages/ops_identity/tests/test_request_transaction.py`)
skip SQL Server unless `OPS_MSSQL_SERVER` and `MSSQL_SA_PASSWORD` are set. On a laptop:

| Task | Command |
|---|---|
| Start the server (127.0.0.1:14330, password generated and kept only in the container) | `deploy/database/mssql_local.sh start` |
| Run a member's tests on both databases, in a Linux client with ODBC Driver 18 | `deploy/database/mssql_local.sh test packages/ops_store -rs tests` |

On Apple silicon the server is Azure SQL Edge (SQL Server engine 15, no Full-Text Search), since the 2022 and 2025
images crash under Docker Desktop's emulation; the pinned 2025 image runs on the SQL Server test machine
(`docs/deploy/fly.md`). A run that prints `SKIPPED ... set OPS_MSSQL_SERVER` did not test SQL Server.

## Gotchas

| Gotcha | Rule |
|---|---|
| `backends()` names only PostgreSQL, so the conformance suites never run on SQL Server here | SQL Server DDL and model parity are checked in `deploy/database/tests` (`make test PKG=deploy/database`, the `pool-deploy` job of `make verify`) |
| The conformance database is `<test database>_conformance`, created on first use | Two sessions with different test databases never migrate each other's |
| Importing `ops_store` installs the connect retry on every SQLAlchemy engine in the process (`src/ops_store/__init__.py:11`) | Engines made in scripts and tests get it without passing anything |

## Reference docs

- [docs/architecture/data.md](../../docs/architecture/data.md): store inventory and data rules
- [docs/architecture/decisions/database-support.md](../../docs/architecture/decisions/database-support.md): PostgreSQL and SQL Server
- [docs/architecture/identity-and-tenancy.md](../../docs/architecture/identity-and-tenancy.md): tenant and team isolation
- [docs/architecture/decisions/fencing-and-timers.md](../../docs/architecture/decisions/fencing-and-timers.md): leases and the database clock

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [data access](../../docs/architecture/standards/data-access.md) (`DA1` to `DA13`), [tenant isolation and access](../../docs/architecture/standards/tenancy-and-access.md) (`TN1` to `TN5`, `AC1` to `AC5`), [events, the relay and workers](../../docs/architecture/standards/events-and-workers.md) (`EV1` to `EV6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
