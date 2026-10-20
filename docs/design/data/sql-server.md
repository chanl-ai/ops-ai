# Running on SQL Server and Azure SQL

Status: current plan beneath [ADR-0017](../../architecture/decisions/database-support.md), partly built. Built: the
dialect ports in `packages/ops_store/src/ops_store/dialect.py`, SQL Server DDL compiled from the store models with
reviewed golden files and tests (`deploy/database/mssql.py`, `deploy/database/tests/test_mssql_ddl.py`), the
portability check (`scripts/check_portable_store.py`) with its shrinking baseline (`portable-baseline.txt`), and the
import contracts in `.importlinter`. Not built yet: the checkpointer on SQLAlchemy Core (it still uses asyncpg), a
registered SQL Server backend for the conformance suites, full-text on SQL Server, and the full test matrix. Where this
plan and ADR-0017 differ, the ADR wins: SQL Server 2025 is the minimum and MySQL is dropped.

## The problem

Banks that standardise on SQL Server cannot run a platform that assumes PostgreSQL. Ops AI was written against
PostgreSQL, but the coupling is narrow: at the time of the inventory, 37 of 435 shipped source files and 53 of 150
migrations used something PostgreSQL-only, and almost all of it sat in store modules. The services above the stores do
not change.

The plan keeps the existing store classes and their interfaces, adds a small dialect port in `packages/ops_store` for
the places the two databases differ (tenant transaction, upsert, row lock, queue claim, clock, full-text), and gives
each service a fresh SQL Server baseline schema built from its store metadata, instead of replaying 150 PostgreSQL
migrations. The same test suites run on both databases through `OPS_TEST_DATABASE_URL`.

## PostgreSQL coupling inventory

Counted over shipped source (`services/*/src`, `packages/*/src`) and migrations. Tests, experiments and scripts were
counted separately because they do not ship. Line-level locations are left out here because the code moves; the
portability baseline file is the current list.

| Feature | Sites | On SQL Server |
|---|---|---|
| asyncpg driver in the checkpointer | 1 file | Rewrite the checkpointer on SQLAlchemy Core |
| Tenant per transaction (`SET LOCAL ROLE`, `set_config('app.tenant_id', …, true)`) | 8 sites, 3 files | Port to `sp_set_session_context` |
| Pre-tenant lookup functions (`SECURITY DEFINER`) | 6 sites, 4 files | Stored procedures `WITH EXECUTE AS` |
| `ON CONFLICT` upsert | 28 sites, 13 files | Fails to compile; needs the upsert port |
| `RETURNING` | 18 sites, 12 files | SQLAlchemy renders `OUTPUT inserted.*`; fails only on tables with triggers (none) |
| `FOR UPDATE SKIP LOCKED` queue claims | 4 claims, 3 files | Silently dropped (see below) |
| `with_for_update()` row locks | 30 sites, 16 files | Silently dropped; needs the lock port |
| Advisory transaction locks | 2 | `sp_getapplock @LockOwner='Transaction'` |
| Clock and interval functions (`extract(epoch, now())`, `make_interval`, `date_trunc`) | 5 sites, 4 files | Runtime error; needs the clock port |
| JSONB operators | 3, all in the checkpointer | Promote the filtered keys to columns |
| Arrays, `= ANY(…)`, `unnest` | 7 sites, 2 files | `IN` lists (2,100-parameter cap) or `OPENJSON` |
| Full-text search (`tsvector`, `ts_rank_cd`, GIN) | 7 sites, 3 files | Full-text index and `CONTAINSTABLE` |
| pgvector | 0 | Not on the critical path |
| `postgresql_where` partial indexes | 3 | Add `mssql_where`; SQLAlchemy ignores the PostgreSQL option silently |
| `timestamptz` | 69 columns | Native `DATETIMEOFFSET` |
| `OFFSET` paging | 19 sites | SQL Server refuses `OFFSET` without `ORDER BY`; the compiler raises, so a test run finds each one |

### Migrations

53 of 150 migrations contained something PostgreSQL-only. 33 of them create row-level security policies, roles or
`SECURITY DEFINER` functions; 28 of those check the dialect first and would skip on SQL Server, leaving no second tenant
check, and 5 run PostgreSQL DDL unconditionally and would fail. One of those 5 is the first revision of the platform
chain, so that chain cannot start on SQL Server at all. This is why the plan uses a fresh baseline per service.

### Schema facts measured from store metadata

| Check | Result | Consequence |
|---|---|---|
| Store metadata against the migrated database | 0 differences for four services, a few for the rest | A baseline generated from metadata matches today's schema; the others need a short reconcile |
| Tables no metadata defines | The three checkpointer tables | The checkpointer must ship a `MetaData` before agents-service can have a baseline |
| Primary keys over 900 bytes, indexes over 1,700 bytes | None across 139 tables | SQL Server's key limits hold under a UTF-8 collation |
| Unique keys over a nullable column | 6 | SQL Server allows one NULL per unique index, so each becomes a filtered unique index `WHERE col IS NOT NULL`, which matches PostgreSQL exactly |
| `Text` columns | 73 of 1,453 | Become `VARCHAR(MAX)`; the database must use a UTF-8 collation or non-Latin text is lost |

## Couplings that fail silently

Most PostgreSQL-only code fails loudly on SQL Server: `postgresql.insert(...).on_conflict_do_nothing()` raises before
reaching the database. Four constructs do not, and these are where a bank would find a bug that PostgreSQL tests never
show. Each was checked by compiling statements with SQLAlchemy's SQL Server dialect.

| Construct | What SQL Server receives | Effect |
|---|---|---|
| `with_for_update()`, including `skip_locked=True` | The plain `SELECT`, with no lock and no error | 30 row locks vanish, including 4 queue claims. Two workers can take the same timer, work item or outbox row, and "lock the team's admins before demoting one" stops serialising. The most dangerous item in the inventory |
| `postgresql_where=` on an index | A full unique index | Indexes meant to apply only to some rows refuse ordinary rows |
| `func.now()` | `CURRENT_TIMESTAMP`, a local time with no offset | Correct only while the server runs in UTC. The port uses `SYSDATETIMEOFFSET()` |
| The `LIKE` escape in the search helper | `%` and `_` escaped, `[` not | In SQL Server `[abc]` is a character class, so a search for `[draft]` matches any one of d, r, a, f, t. The escape must add `[` |

## Mapping to SQL Server and Azure SQL

| PostgreSQL today | SQL Server and Azure SQL | Plan |
|---|---|---|
| Row-level security on `current_setting('app.tenant_id')` | Security policy with FILTER and BLOCK predicates on `SESSION_CONTEXT(N'tenant_id')`. Session context lasts for the connection, not the transaction | The port sets and clears it per transaction |
| `SECURITY DEFINER` functions | Stored procedures `WITH EXECUTE AS` a user without login | Four procedures, platform only |
| JSON and JSONB | `NVARCHAR(MAX)` with `OPENJSON` and `JSON_VALUE`; a native json type on 2025 and Azure SQL | Keep `sa.JSON`; no SQL filters inside JSON (a filtered field is a column) |
| `ON CONFLICT` | `MERGE … WITH (HOLDLOCK)` for update; `INSERT … WHERE NOT EXISTS (… WITH (UPDLOCK, HOLDLOCK))` for do-nothing | `upsert` and `insert_ignore` ports |
| `RETURNING` | `OUTPUT inserted.*` | No change |
| `FOR UPDATE SKIP LOCKED` | `SELECT TOP (1) … WITH (UPDLOCK, READPAST, ROWLOCK)` in a CTE, then `UPDATE … OUTPUT` | `claim` port |
| `FOR UPDATE` | `WITH (UPDLOCK, ROWLOCK)` | `locked` port at every site |
| Advisory transaction lock | `sp_getapplock` with a transaction owner | `lock_key` port |
| `now()`, epoch, intervals | `SYSDATETIMEOFFSET()`, `DATEDIFF_BIG`, `DATEADD` | `db_now`, `db_epoch`, `db_after` ports |
| `tsvector` with GIN, `ts_rank_cd` | A full-text index; on Linux it needs the `mssql-server-fts` package, which the default image lacks; built into Azure SQL | `full_text` port; a custom image for on-premises installs; tests wait for asynchronous population |
| pgvector (not used yet) | `VECTOR(n)` on 2025 and Azure SQL; the vector index is preview on 2025 | When knowledge adds embeddings: exact distance over a tenant-filtered set on 2025, an approximate index on Azure SQL |
| Partial index | Filtered index (simple predicates only) | `mssql_where` beside each `postgresql_where` |
| Case-sensitive UTF-8 text | A database created with `Latin1_General_100_BIN2_UTF8` | The migrate job refuses any other collation |
| Readers never block writers | `READ_COMMITTED_SNAPSHOT` is off by default on SQL Server, on by default on Azure SQL | The migrate job sets or checks it |

## Driver and sign-in

| Option | Async | Choice |
|---|---|---|
| `mssql+aioodbc` (ODBC Driver 18) | Yes. Calls run in a thread pool, so throughput per process is lower than asyncpg | Used |
| `mssql+mssqlpython` | No; every store would need `run_sync` | Revisit when an async dialect ships |
| pymssql | No; no Entra ID token support | Not used |

| Where | Sign-in |
|---|---|
| A bank's own SQL Server | SQL login (Windows or Kerberos where the bank requires it); `Encrypt=yes`, and `TrustServerCertificate=yes` only for a test container |
| Azure SQL from Azure compute | Microsoft Entra ID managed identity, or an access token passed at connect time and refreshed before it expires |
| Azure SQL from outside Azure | An Entra ID service principal whose secret is read from a mounted file |

## Architecture

Each service keeps its store classes and their method signatures. Routers, the engine and the agent runtime call the
same methods and do not learn which database is underneath.

| Layer | Change |
|---|---|
| Routers, services, engine runtime | None |
| Store classes | Each PostgreSQL-only call becomes a port call: a dialect insert becomes `upsert(...)`, `.with_for_update()` becomes `locked(q, table)`, `func.now()` becomes `db_now()` |
| `ops_store.dialect` | The ports, each choosing its renderer from the connection's dialect (PostgreSQL, SQL Server, and SQLite for unit tests) |
| `ops_store` backends | A SQL Server backend registered with all guarantees, so the existing conformance suites (leases, timer claims, audit) run on it |
| Baseline and security | A service's SQL Server schema compiled from its metadata, then the security policy, lookup procedures, full-text catalog and filtered unique indexes |
| Checkpointer | Rewritten on SQLAlchemy async Core with a `MetaData` for its three tables; same serializer and blob format |
| Tests | The same tests; `OPS_TEST_DATABASE_URL` selects the database |

Ports were chosen over an ORM or a second store implementation per database because the differences sit in about 120
call sites. A second copy of every store would double the code a reviewer reads and keep the same 120 differences; a
port puts each difference in one function with a conformance test on both databases.

## Tenant isolation on SQL Server

The store filter (`tenant_id = :t` in every statement) stays the first control on every database. The security policy
is the second, matching PostgreSQL row-level security.

| PostgreSQL | SQL Server |
|---|---|
| A policy on `current_setting('app.tenant_id')`, forced on every tenant table | Two schema-bound inline functions per service. The read function admits a row for the session's tenant, for the system flag, or for the lookup user, and is bound as the FILTER predicate. The write function checks the tenant alone and is bound as BLOCK predicates after insert and after update, so the system flag and the lookup user read and never write |
| `SET LOCAL ROLE` and `set_config(…, true)`, reverted at commit | `sp_set_session_context` for the tenant and the system flag at the start of every tenant transaction, both cleared in a `finally`, and `sp_reset_connection` when the pool takes the connection back. Session context is not transaction-scoped, so without this the next borrower of the connection inherits the previous tenant |
| A system transaction that reads every tenant | Tenant NULL and system flag 1: reads every tenant, writes nothing |
| Superuser bypasses row-level security unless it switches role | Security policies apply to `db_owner` too; only someone who can alter the policy can turn it off |

The tenant isolation tests run unchanged on both databases. SQL Server adds one failure mode with its own test: a
connection used for tenant A, returned to the pool and borrowed with no tenant, sees nothing.

## Migrations

A fresh SQL Server baseline per service, stamped at that service's current head. The PostgreSQL chains stay as they
are, and every migration written after the baseline runs on both databases.

| Option | For | Against |
|---|---|---|
| Fresh baseline per service (chosen) | No SQL Server database exists yet, so there is no history to upgrade; the platform chain cannot start on SQL Server; store metadata already equals the migrated schema for most services | Two ways to reach the same schema, so a parity test must keep them equal |
| Make all 150 migrations dialect-aware | One path | 53 files to rework, including tables that no longer exist, and applied migrations must not be edited |

| Mechanism | Detail |
|---|---|
| Where the baseline comes from | Compiled from the store models with no server, reviewed as golden SQL files per chain, and checked by a test that the files equal what the models compile to |
| Preconditions the migrate job checks | UTF-8 binary collation, `READ_COMMITTED_SNAPSHOT` on, full-text installed (knowledge only), a recent compatibility level |
| Parity in CI | PostgreSQL after its chain equals the store metadata, and PostgreSQL after its chain equals SQL Server after its baseline (tables, columns, nullability, unique keys, indexes). A migration that changes one without the other fails the build |
| Migrations after the baseline | Written with Alembic operations and the dialect helper only, and run on both databases in CI |

## Proof

| Proof | How |
|---|---|
| Every suite on SQL Server | `OPS_TEST_DATABASE_URL` pointing at a SQL Server database created with the UTF-8 binary collation |
| Conformance | Leases, timer claims and audit, plus suites for `claim` (one winner among 20 contenders, oldest due row first), upsert under concurrency, `lock_key`, and the pooled-connection tenant leak |
| Tenant isolation | The isolation tests, with the store filter switched off in one test so the security policy alone is shown to hold |
| Install walk | The compose proof on a fresh SQL Server database: migrate, connect the model, sign in, chat, upload, run a workflow, read a document, open the console pages |
| Azure SQL | A scheduled job against a real Azure SQL database with managed identity, which a container cannot prove |

A note for developers on Apple Silicon: the SQL Server images are amd64 only and crash under QEMU emulation; they run
under Docker Desktop's Rosetta emulation, and authoritative runs belong on amd64 machines.

## Phases

Estimates are engineer-days for one engineer who knows the repository, tests included.

| # | Slice | Done when | Days |
|---|---|---|---|
| 0 | SQL Server dev container and driver; the live-database guard covers SQL Server URLs; the `LIKE` escape adds `[` | A test fixture reads `SELECT @@VERSION` | 1-2 |
| 1 | Dialect ports with PostgreSQL, SQL Server and SQLite renderers; a lint that flags raw locks, `func.now()` and dialect inserts outside the port | Conformance suites green on both databases, each new suite seen red against a renderer with its lock removed | 4-5 |
| 2 | Baseline and parity for every chain | Every baseline builds; parity green for the first services | 3-4 |
| 3 | First slice: files, documents, models; the migrate job takes a database URL per chain so these run on SQL Server beside PostgreSQL | Three suites green on both; an install with those services on SQL Server migrates and starts | 4 |
| 4 | Platform and tenant isolation | Platform suite and isolation tests green on both | 4-5 |
| 5 | Tools | Tools suite green on both | 3-4 |
| 6 | Engine and agents stores | Agents suite (without the checkpointer) green on both; the worker crash test green on SQL Server | 6-8 |
| 7 | Checkpointer on SQLAlchemy Core | LangGraph's checkpointer suite green on both; write p95 within 10% of asyncpg on PostgreSQL | 5-7 |
| 8 | Knowledge full-text | Knowledge suite and the cited-answers use case green on both | 4-5 |
| 9 | Install proof, CI matrix, Azure SQL job, supported-database page | The install proof passes on SQL Server | 3-4 |
| | Total | | 37-48 |

Slices 0 to 2 are the critical path. After slice 2, slices 3, 4 and 5 can run in parallel, and 7 can start beside 6:
about 4 to 5 weeks with two engineers, 7 to 9 with one. Vectors are outside this plan because knowledge stores no
embeddings yet.

## Risks

| Risk | Detail | Handling |
|---|---|---|
| Silent lock loss | `with_for_update` renders nothing on SQL Server | The portability check fails a new raw lock; conformance suites prove each lock with contenders |
| Throughput | aioodbc runs calls in a thread pool; lock escalation at about 5,000 row locks; deadlocks are error 1205 instead of PostgreSQL's 40P01 | Pool sizing, deadlock retry in the port, load targets measured on SQL Server |
| Readers blocking writers | Locking `READ COMMITTED` by default on SQL Server | The migrate job refuses a database without `READ_COMMITTED_SNAPSHOT` |
| Gaps in the security policy | Session context outlives the transaction; schema-bound predicate functions block altering the columns they reference; predicates can leak row existence through error side channels | The port clears context and the pool resets connections; a migration helper drops and recreates the policy around tenant-column changes; the store filter stays the first control |
| JSON indexing | A JSON path cannot be indexed portably | A filtered field is a column |
| Full-text differences | Different stemming and ranking, asynchronous population, word breakers changed in 2025 | Ranking floors per dialect; tests wait for population |
| Behaviour that passes PostgreSQL tests | NULLs sort first ascending on SQL Server and last on PostgreSQL; trailing spaces are ignored in `=`; at most 2,100 parameters per statement | Lists sort on non-null columns or state `nulls_last()`; the port chunks `IN` lists; CI runs every suite on both |
| Licensing for testers | Developer edition is free for development and test only | Development and CI use Developer edition; a bank brings its own licence |

## What PostgreSQL code stops doing

To keep both databases working, code outside `ops_store` gives up these PostgreSQL features. Existing uses move behind
the ports in the slice that owns them, and the portability baseline only falls.

| Stop | Use instead |
|---|---|
| `postgresql.insert(...).on_conflict_*` | `upsert`, `insert_ignore` |
| `.with_for_update()`, `skip_locked`, advisory locks | `locked`, `claim`, `lock_key` |
| `func.now()`, `extract('epoch')`, `date_trunc`, `make_interval`, `interval '…'` | `db_now`, `db_epoch`, `db_after` |
| JSONB, JSON operators, arrays, `ANY(:list)` | `sa.JSON` read whole; promoted columns; `in_()` through the chunking helper |
| `postgresql_where` alone, GIN, expression indexes | An `mssql_where` twin, or a plain index over a column |
| New `SECURITY DEFINER` functions, `DO $$` blocks, policies written inline in a migration | The dialect security helper, which writes both forms |
| Tests reading `pg_*` catalogs for a portable property | `sa.inspect` |
| Raw `sa.text` DML in stores | Core statements, or a port with a renderer per dialect |
