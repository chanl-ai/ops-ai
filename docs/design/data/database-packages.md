# Database code in store packages

Status: current, built. The contracts are in `.importlinter`, run by `uv run lint-imports` in `make python-verify` and
the commit gate (`scripts/verify-staged.sh`). The `Database` handle and `open_database` are in
`packages/ops_store/src/ops_store/database.py`. The tables per service are described in
[architecture/data.md](../../architecture/data.md); the database decision is
[ADR-0017](../../architecture/decisions/database-support.md).

## The problem

Every service owns its own tables, and the platform runs on two databases (PostgreSQL and SQL Server). Both only hold
if database code stays in one known place per service. When a route, a graph or a seed script builds its own engine or
writes its own query, three things break: a second database has to be supported in places nobody listed, a service
can reach another service's tables, and a PostgreSQL-only construct slips in where the portability check does not look.

When this design was written, database code already sat mostly in each service's `store` package, but six source files
outside stores imported a driver or SQLAlchemy (engine construction in entry points, and one service whose roughly 19
queries lived in its app module), plus dev scripts and experiments that no rule scanned. No service imported another
service's store.

| Area | Store | Migrations | Tenant isolation |
|---|---|---|---|
| agents-service | `ops_agents/store/`, plus `ops_engine/store` used only by agents-service | Own chain | Row-level security through its tenancy module |
| platform-service | `ops_platform/store/` | Own chain | Row-level security through its tenancy module |
| tools-service, files-service, documents-service, kb-service | `ops_<svc>/store/` | Own chain each | Store filter |
| models-service | Tables only, with queries in the app module (since moved into `ops_models/store/`) | Own chain | Store filter |

Each service's `migrations/env.py` imports its store's `MetaData` and filters to its own tables, with its own version
table: database per service on a shared server.

## Practices this follows

| Practice | Source | What it says | How it applies |
|---|---|---|---|
| Repository | *Architecture Patterns with Python*, chapter 2 | A repository is an abstraction over persistent storage; for simple CRUD it may not pay for itself | Stores are repositories; no abstract base class per store |
| Unit of work | Same book, chapter 6 | Keep session, transaction and exception management away from business code | `ops_store` owns the tenant transaction; handlers never open one |
| Ports and adapters | Alistair Cockburn, hexagonal architecture | The inside must not leak into the outside; the database is swappable like a UI | `ops_store.ports` and `ops_store.dialect` are the port; the per-dialect renderers are the adapters |
| Database per service | microservices.io | Data is private to a service and reached through its API; a shared database is an anti-pattern | Each service's tables stay private; there is no shared schema package |
| Migrations beside models | Django; Alembic's multiple chains | Each app's migrations live with it | One chain per service, each with its own version table |
| Boundary enforcement | import-linter contract types | Forbidden, layers, independence and protected contracts, with `ignore_imports` and alerting on unmatched ignores | The contracts below |
| Real databases in tests | Testcontainers | Test against a real database, not a mock | Store suites run per dialect |

## The layout

The data package is the existing `ops_<svc>.store` sub-package, not a new distribution per service. A separate
distribution would add seven `pyproject.toml` files and rewrite imports in about 175 test files, and import-linter
gives the same isolation on a sub-package.

| Piece | Lives in | Imports a driver? |
|---|---|---|
| Tables (one `MetaData` per service), repositories, the service's dialect branches | `services/<svc>/src/ops_<svc>/store/` | Yes |
| Migrations | `services/<svc>/migrations/` | Yes |
| Engine factory, `Database` handle, tenant transaction, upsert, row lock, queue claim, app lock, clock, full-text, schema version | `packages/ops_store` | Yes |
| Everything else: routes, graphs, activities, entry points, seeds, scripts | The rest of the service | No |

Code outside a store receives a `Database` handle and a repository object. It never sees `AsyncEngine`, a connection
or a table. Entry points call `open_database(settings.database_url)`.

## The contracts

| Contract | Type | Rule |
|---|---|---|
| Drivers only in stores | Forbidden | No `ops_*` package imports SQLAlchemy, asyncpg, the ODBC drivers or Alembic, except a store package, `ops_store` and the checkpointer |
| The ignore list only shrinks | Same contract | `unmatched_ignore_imports_alerting = error`: a listed crossing whose import is gone fails the run, so the list can only get shorter |
| A store is the bottom of its service | Forbidden, one per service | `ops_<svc>.store` imports nothing else in `ops_<svc>` |
| Services are independent | Independence | No service package imports another |
| Libraries sit below services | Forbidden | `ops_store`, `ops_engine`, `ops_checkpointer`, `ops_identity`, `ops_service_kit`, `ops_policy`, `ops_metering` and the other libraries never import a service |
| SQL text stays portable | Script | `scripts/check_portable_store.py` catches `postgresql_*` options, `RETURNING` and `ON CONFLICT`, which import-linter cannot see |

Migrations are not a package, so they sit outside import-linter; each `env.py` is covered by a store test.

## Trade-offs

| Decision | Cost | Reason |
|---|---|---|
| A sub-package, not a new distribution | A service can still reach `ops_x.store.tables` from outside | Lower churn; add a protected rule only if that happens |
| A `Database` alias hides `AsyncEngine` | One more name | A SQL Server engine or a pool change touches only `ops_store` |
| Repositories without abstract base classes | Not swappable for an in-memory fake | Tests use a real database |
| The tenant transaction lives in `ops_store` | A shared-package change affects every service | SQL Server's security policy needs it, behind the existing `tenant_tx` signature |

## What not to do

| Don't | Why |
|---|---|
| Create a shared `ops_data` package with every service's tables | It couples releases and breaks database per service |
| Let `ops_store` import a service, or a service read another service's tables | It inverts the dependency direction |
| Move migrations into one shared chain | Each service keeps its own version table and releases on its own |
| Rewrite a store while moving it | Move first, convert to portable constructs second, one commit each, so a review sees one kind of change |
| Add a repository interface per table, or pass connections out of a store to hide a leak | The leak is still there, now harder to find |
| Widen `ignore_imports` to make the gate pass | The list only shrinks |
| Regenerate the portability baseline to hide a finding | Same rule |
| Mock the database in store tests | Run them per dialect through the `ops_store` conformance suite |
