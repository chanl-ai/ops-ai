# The database: install, upgrade and verify from reviewed scripts

Status: current for PostgreSQL, proven on a throwaway server. For SQL Server and Azure SQL the scripts are generated
and reviewed, and not yet applied to a server ([SQL Server](#sql-server-and-azure-sql)).

<!-- PostgreSQL: an earlier change, proof deploy/database/proof.sh. SQL Server: an earlier change (DIALECT=mssql), first apply is an earlier change. -->

A bank's DBA applies every schema change in their own change window and never runs Ops AI's code against
production. Each service's migration chain stays the source, and every script below is generated from those chains
and never edited by hand.

The chains are in `deploy/images/chains`, one Alembic chain per service, and `deploy/database/schema.py` generates the
scripts.

## Who runs what

| Step | Runs it | Connects as | Script |
|---|---|---|---|
| Roles, once per server and again when a release adds one | DBA | a superuser | `roles.sql`, `upgrade-roles.sql` |
| Create the database | DBA | a superuser | `CREATE DATABASE <name> OWNER ops_migrator;` |
| Fresh install | DBA | `ops_migrator` | `bundle.sql`, then `grants.sql` |
| Upgrade | DBA | `ops_migrator` | `upgrade.sql`, then the new release's `grants.sql` |
| Run the services | the platform team | one login per service, `ops_<service>_runtime` | none: each refuses to start on a schema behind it |
| Check | DBA or platform team | any login that reads the schema | `make db-drift` |

| Role | Rights |
|---|---|
| `ops_migrator` | Owns every table, index, policy and sequence; not a superuser, cannot create roles or databases. May switch to the roles below |
| `ops_<service>_runtime` (agents, tools, models, kb, platform, files, documents) | Logs in; SELECT, INSERT, UPDATE, DELETE on its own service's tables, its sequences, SELECT on its version table. No DDL: `CREATE TABLE` and `DROP TABLE` are refused (proof check 3). Not a superuser and no BYPASSRLS, so row-level security applies, and the tables that carry tenant policies are FORCEd |
| `ops_runtime_tenant`, `ops_runtime_system`, `ops_platform_tenant`, `ops_platform_lookup` | No login. The services switch to them per transaction (`SET LOCAL ROLE`); each runtime role is a member of the ones its own tables grant to. `ops_runtime_system` bypasses RLS and is used only by agents-service's sweeper, timer and inbox loops |

## Day one: a fresh install

```
make db-ddl SERVER=postgresql://postgres:<pw>@<throwaway host>:5432/postgres REF=<release tag> OUT=dist/db/<tag>/baseline
```

`SERVER` is a throwaway server the tool may create and drop scratch databases on, and where the chains' roles get
made: never production. `REF` is exported with `git archive`, so uncommitted files never reach a script.

| File | What it holds |
|---|---|
| `roles.sql` | Every role above, each guarded so it can run again; set each login's password afterwards (`ALTER ROLE ... PASSWORD`) |
| `01-agents.sql` ... `07-documents.sql` | The objects each service's chain creates, for review. Apply the bundle, not these |
| `bundle.sql` | The whole schema in the server's dependency order: tables, constraints, indexes, row-level security and policies, grants to the no-login roles, and the rows a fresh migration writes (each chain's version row) |
| `grants.sql` | Each runtime role's rights, its membership of the no-login roles its tables grant to (granted only where it is missing, so a role a later migration added reaches a login roles.sql made before it), and CREATE on the public schema revoked from everyone but its owner (some server templates grant it to all; Fly's PostgreSQL 18 did); every statement can run again |
| `manifest.json` | The commit, dialect, each chain's head revision, version table, runtime role and tables, and every file's sha256 |
| `SHA256SUMS` | `shasum -a 256 -c SHA256SUMS` checks the files arrived unchanged |

The DBA then runs, with their own tools:

```
psql -v ON_ERROR_STOP=1 "postgresql://<superuser>@<host>/postgres" -f roles.sql
psql "postgresql://<superuser>@<host>/postgres" -c "CREATE DATABASE ops OWNER ops_migrator"
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f bundle.sql
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f grants.sql
```

and gives each service its own login in its DSN: `OPS_DATABASE_URL_<SERVICE>` in `deploy/compose/app.env.example`.
The baseline applied this way equals what the chains build: proof check 1 compares the two and finds no difference.

## Day 20: an upgrade

```
make db-upgrade-sql FROM=<running release> TO=<new release> OUT=dist/db/<new>/upgrade-from-<running>
```

| File | What it holds |
|---|---|
| `upgrade-roles.sql` | Statements only a superuser may run (a new role), guarded; run first |
| `upgrade.sql` | One step per revision, chains in migrate order. Each step names its chain and revisions and its sha256, checks the version row it starts from (and raises before any DDL when the database is elsewhere), runs in its own transaction, and records its new version row |
| `downgrade.sql` | The reverse steps where the revision has a downgrade; a step without one says to restore a backup |
| `SHA256SUMS` | As above |

After `upgrade.sql`, run the new release's `grants.sql`, so new tables reach their runtime role. Proof check 2 applies
an older baseline plus the upgrade and finds no difference from the newer schema; check 2b runs the upgrade again and
the first guard refuses it. Eight revisions applied before offline rendering was a rule cannot render as SQL (agents
0031, 0036, 0042; tools 0001, 0020; platform 0006, 0013, 0017); an upgrade across one is refused by name, and a
release after them installs from its baseline. `deploy/database/tests/test_offline.py`, run by `make verify`, keeps
every later revision renderable.

### An index on a large live table

`CREATE INDEX` holds writes on its table until it is built, and `upgrade.sql` runs each step in a transaction, where
`CREATE INDEX CONCURRENTLY` cannot run. The index steps that may meet a large table create the index only when it is
missing (agents 0071, an earlier change: the work queue, live workflow versions, thread lists and event polls, runs by workflow
and checkpoints by run). On a table over about a million rows, build the index by hand first, outside a transaction,
with the name and columns the revision gives, for example
`CREATE INDEX CONCURRENTLY ix_engine_runs_workflow_created ON engine_runs (tenant_id, workflow_id, created_at)`;
the upgrade then finds it and goes on.

## Verify: drift

```
make db-drift DATABASE=<live database URL> SERVER=<throwaway server URL>
```

It reads the live database's version rows, migrates a scratch database to exactly those revisions, and lists every
object that is missing, extra or different, then exits 1 when there is any. Proof check 4 adds an index by hand and
drift names it (`extra INDEX ix_by_hand`), then goes green once it is dropped. Grants to the runtime roles and the
migrator are left out: an install adds them, a migration never does.

## Start check

Each service (the worker included) reads its chain's head from its own migrations and refuses to start unless the
database records it (`packages/ops_store/src/ops_store/schema_version.py`):

```
SchemaBehindError: models-service: the database's schema is behind: it records models_0005, this build needs models_0006. Apply the upgrade first.
```

A database that records none of the build's revisions (not installed, or a newer release's schema under an older
image) is refused too.

## Roll back

Migrations do not roll back on their own. Either run `downgrade.sql` (as the migrator, where every step has a
downgrade) and deploy the older images, or restore the database backup taken before the upgrade. A service of the
older release refuses to start on the newer schema, so the two cannot be mixed by accident.

## Releases

Release tags do not exist yet, so `FROM`, `TO` and `REF` take any git ref. `make db-release SERVER=<url> TAG=<tag>
FROM=<previous tag>` writes `dist/db/<tag>/baseline/` and `dist/db/<tag>/upgrade-from-<previous>/`; attach both to the
tag's release (`gh release upload <tag> dist/db/<tag>/**/*`). Tagging and uploading are done by hand; no CI job does
it yet.

## Proof

```
sh deploy/database/proof.sh [FROM]          # FROM defaults to c60afb6c; a throwaway PostgreSQL 17 of its own
```

| Check | What it shows |
|---|---|
| 1 | The HEAD baseline on an empty database equals the schema Alembic builds |
| 2, 2b | FROM's baseline plus the upgrade equals HEAD; running the upgrade again is refused before any DDL |
| 3, 3b, 3c, 3d | A runtime role reads and writes its tables, is refused CREATE TABLE and DROP TABLE, cannot read another service's tables, and may write a table its code declares that another chain created |
| 4, 4b, 4c | Drift is green on a clean install, red on a hand-made index, green again once it is dropped |
| 5 | models-service at HEAD refuses to start on FROM's schema |

`deploy/compose/proof.sh` installs the same baseline on a throwaway server and runs the whole compose stack with each
service on its own login (walk 13 of 13); Fly staging runs the
same way (`docs/deploy/fly.md`).

## SQL Server and Azure SQL

SQL Server 2025 or later, and Azure SQL Database (ADR-0017). The same targets take `DIALECT=mssql` and need no
`SERVER`: the baseline is compiled from each service's store models with SQLAlchemy's SQL Server dialect
(`deploy/database/mssql.py`), because 53 of the 150 PostgreSQL migrations hold SQL that SQL Server cannot run.
`test_model_parity.py` holds the models equal to what the migrations build on PostgreSQL. Every file is a sqlcmd
script: run each with `sqlcmd -b`, which stops at the first error.

```
make db-ddl DIALECT=mssql REF=<release tag> OUT=dist/db/<tag>/baseline
```

| File | What it holds |
|---|---|
| `roles.sql` | In master, as a server administrator: one SQL login per service plus `ops_migrator`, each password a sqlcmd variable (`-v ops_migrator_password=...`); the database with collation `Latin1_General_100_BIN2_UTF8` and `READ_COMMITTED_SNAPSHOT ON`, owned by `ops_migrator` |
| `01-agents.sql` ... `07-documents.sql` | Each chain's tables, indexes, keys and defaults, its security policies, and its version table stamped at the chain's head. For review |
| `bundle.sql` | As `ops_migrator` in the database: refuses a database with another collation, without READ_COMMITTED_SNAPSHOT or below compatibility level 160, then every chain's file |
| `grants.sql` | As `ops_migrator`: a database user per service login, with SELECT, INSERT, UPDATE and DELETE on its own tables and SELECT on its version table, and nothing else; then the user `ops_runtime_system` (no login) with exactly the grants PostgreSQL's role of that name has, and IMPERSONATE on it for `ops_agents_runtime` alone (below); run again after every upgrade |
| `manifest.json`, `SHA256SUMS` | As for PostgreSQL, with each chain's SQL Server baseline revision and anything left out |

```
sqlcmd -b -d master -i roles.sql -v database=ops ops_migrator_password=... ops_agents_runtime_password=... (one per service)
sqlcmd -b -U ops_migrator -d ops -i bundle.sql
sqlcmd -b -U ops_migrator -d ops -i grants.sql
```

| Difference from PostgreSQL | SQL Server form |
|---|---|
| Forced row-level security on each tenant-scoped table, one generated policy each (`{t}_tenant`, or `{t}_isolation` for a team-owned table) | A security policy per table (`ops_security.<table>_tenant` or `_isolation`) binding a FILTER predicate and BLOCK predicates AFTER INSERT and AFTER UPDATE, generated with the PostgreSQL policy from the table's markings by `ops_store.schema.security_ddl`. The predicates read `SESSION_CONTEXT(N'tenant_id')`, and for a team-owned table `team_id` and `scope`, which `ops_store.isolation.isolated_tx` sets and clears per transaction: a team transaction reads its team's rows and the null-team rows and writes only its team's; a tenant-wide one (a named `tenant_wide` reason) reads and writes every team of its tenant. agents-service and platform-service go through it (platform's pre-tenant lookup functions are still PostgreSQL-only, listed below); the checkpointer still sets the tenant with PostgreSQL-only statements of its own, so on SQL Server it sees no rows until its conversion card. The agents predicates also pass every tenant for `USER_NAME() = N'ops_runtime_system'`, a user without a login that `ops_store.isolation.system_tx` (with a named reason) enters with `EXECUTE AS USER` and reverts; only `ops_agents_runtime` holds IMPERSONATE on it, and no session value a login sets for itself opens another tenant's rows. A row predicate cannot limit columns, so what that user reads and updates is held by its grants, as PostgreSQL's BYPASSRLS role `ops_runtime_system` is: SELECT on graph_threads, graph_runs, thread_events, review_decisions, review_approvals and engine_definitions, SELECT and UPDATE on engine_work, SELECT on `agent_memories (tenant_id)` only, nothing on mailboxes (`SYSTEM_READS` in `mssql.py`, held equal to the migrated PostgreSQL grants by `test_model_parity.py`) |
| A unique key over a nullable column admits any number of NULL rows | A filtered unique index `WHERE <column> IS NOT NULL`, which admits the same rows |
| A partial index | A filtered index from its `mssql_where` twin; a partial index without one is refused by name |
| `text`, JSON, `timestamptz`, `boolean`, serial keys | `VARCHAR(max)` (UTF-8 under the collation), `NVARCHAR(max)`, `DATETIMEOFFSET`, `BIT`, `IDENTITY` |
| Unnamed keys | Named as PostgreSQL names them (`<table>_pkey`, `<table>_<columns>_key`, `<table>_<columns>_fkey`), so a later migration names the same object on both |

Upgrades: `make db-upgrade-sql DIALECT=mssql FROM=<running release> TO=<new release>` writes `upgrade.sql` and
`downgrade.sql` from Alembic's offline SQL for SQL Server, one guarded step per revision (`THROW` when the version row
is elsewhere, `SET XACT_ABORT ON`), then run the new `grants.sql`. A step's statements that SQL Server refuses inside a
transaction (the full-text catalog and index) run after its `COMMIT`, in their own batch. A range that starts before a
chain's pin (`BASELINE` in `mssql.py`) is refused by name, as is a step whose offline SQL holds PostgreSQL-only SQL.
SQL Server upgrades start from the first release whose bundle installs, the release cut after an earlier change: no SQL Server
install of an earlier release exists, so the pins move to that release's heads when it is cut. Until a migration lands
after it there is nothing to upgrade. `deploy/database/mssql_live.py drift` compares an installed database with the
models; `make uc-sql-server` installs the bundle on the SQL Server test machine and runs it (uc-565).

| Not on SQL Server yet | Owner |
|---|---|
| kb's full-text column `kb_chunks.tsv` and its GIN index (left out, listed in the kb file and the manifest) | kb's full-text card |
| Platform's four pre-tenant lookup functions | the platform port |
| A live run of `isolated_tables` on `sys.security_policies` (written, never run on a server) and of the isolation suite; a live check that `EXECUTE AS USER` and the column grant hold on a server | an earlier change on the an earlier change machine |
| An upgrade applied to a SQL Server install (uc-565 S2) | the first migration after the first installable release |

`deploy/database/tests/test_mssql_ddl.py` compiles the models and compares every file with the reviewed golden files
in `deploy/database/golden/mssql/`; a model change fails it naming the chain's file. Review the new DDL, then
`make db-ddl-golden`.

## Facts that shape it

| Fact | Consequence |
|---|---|
| Eight applied revisions read rows or inspect tables, and an applied migration is never edited | The baseline is a dump of a database the chains just migrated, not their offline SQL |
| A constraint built through SQLAlchemy and the same constraint restored from a dump deparse differently | Every comparison restores both sides once before comparing |
| pg_dump refuses a server newer than itself | The dialect uses a local pg_dump of the server's version or newer, else the matching `postgres` image |
| Roles are server-wide | Generate and prove on a throwaway server, never the shared dev cluster |
