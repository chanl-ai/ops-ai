# ADR-0017 Database support

Status: decided by the owner, 2026-10-19 (epic c-337). Unlike ADR-0001 to ADR-0016, this one is not an option.

## Context

A bank installs Ops AI on the database it already licenses and runs. Until now only PostgreSQL ran, with MySQL 8 and
Azure SQL named as planned. The owner chose SQL Server as Ops AI's own database beside PostgreSQL, so a bank that
standardises on SQL Server needs no PostgreSQL at all. The design and inventory are in
[design/data/sql-server.md](../../design/data/sql-server.md).

## Decision

| Item | Decision |
|---|---|
| Supported databases | PostgreSQL, and SQL Server 2025 or later. Azure SQL Database runs the same engine and comes first in intent; it is tested once someone has Azure access |
| Dropped | MySQL. Nothing is written or tested for it |
| Minimum SQL Server | 2025: the json and vector types exist there; 2022 is not supported |
| Sign-in | SQL logins now; Microsoft Entra ID (managed identity, service principal) with Azure SQL later |
| Driver | `mssql+aioodbc` (ODBC Driver 18) for SQL Server; `postgresql+asyncpg` for PostgreSQL |
| Test server | SQL Server 2025 Developer edition on one Fly machine (`<your-app>-mssql`), never on a laptop (c-345) |

## The rule every change follows

| Part | What it means | Enforced by |
|---|---|---|
| Two databases in every test run | Each service's store tests run on PostgreSQL and SQL Server through `OPS_TEST_DATABASE_URL`; a pair that passes is green, a split is red | The matrix in verify-head and `make python-verify` (c-345) |
| Differences live in one place | Stores build statements with SQLAlchemy Core. Where the two databases differ (upsert, row lock, queue claim, app lock, database clock, tenant transaction, full-text; vectors later) a store calls `ops_store.dialect` | `scripts/check_portable_store.py --strict` in the commit gate and `make python-verify` (c-343) |
| The baseline only falls | `portable-baseline.txt` lists the code that does not run on SQL Server yet. A commit that raises a row carries a `Standards-exception:` trailer the orchestrator approved | `check_portable_store.py --commits` (c-343) |
| One schema source | Store metadata is the schema (c-342); SQL Server DDL is compiled from it (c-344). Each chain gets a SQL Server baseline stamped at its current head, and every migration after it is written with Alembic operations that run on both | `deploy/database/tests/test_model_parity.py` (c-342) and the SQL Server DDL tests (c-344) |
| Database code in stores only | Only a service's store package, `ops_store` and the checkpointer import a driver or SQLAlchemy | `lint-imports` (`.importlinter`, c-346) |

## Consequences

- PostgreSQL-only constructs (ON CONFLICT, SKIP LOCKED, advisory locks, JSONB operators, `postgresql_where` alone) stop
  appearing outside `ops_store`. A partial index gives `postgresql_where` and `mssql_where` together.
- `with_for_update()` renders nothing on SQL Server, so a row lock is taken with `ops_store.dialect.locked` or `claim`.
- Tenant isolation on SQL Server is a security policy over `SESSION_CONTEXT`, set and cleared every transaction,
  generated from the `TENANT_SCOPED` marker.
- The existing 150 PostgreSQL migrations are not replayed on SQL Server.

## What would change it

A bank that needs another database, or Azure SQL behaviour that differs from SQL Server 2025 in a way the tests show.
