# Database

Status: current for PostgreSQL, proven on a throwaway server. SQL Server 2025 and Azure SQL are partial: see
[SQL Server and Azure SQL](#sql-server-and-azure-sql).

Set up and change Ops AI's database the way a bank's DBA works: from reviewed SQL scripts, in your own change window,
without running Ops AI's code against production. Every script is generated from the release and never edited by hand,
and each service runs on its own login that cannot change the schema.

## Choose who applies the schema

| Mode | Who applies it | Use it when |
|---|---|---|
| Automatic | The install's schema job, with a superuser login you give it | A trial, or a database Ops AI owns |
| DBA | Your DBA, from the release's scripts | Production: the services never hold a login that may change the schema |

The [install script](install.md) asks which (`--db-mode auto` or `--db-mode dba`). In DBA mode it writes the scripts
to `./dba/` and prints the commands below. A [release package](release-package.md) carries the same scripts under
`db/postgres/`.

## Install on PostgreSQL

You need PostgreSQL 15 or newer, or Azure Database for PostgreSQL Flexible Server 16 or newer, with the `vector`
extension offered.

```bash
shasum -a 256 -c SHA256SUMS
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/postgres" -f roles.sql
psql "postgresql://<admin>@<host>/postgres" -c "CREATE DATABASE ops OWNER ops_migrator"
psql "postgresql://<admin>@<host>/ops" -c "CREATE EXTENSION IF NOT EXISTS vector"
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f bundle.sql
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f grants.sql
```

Then set each login's password (`ALTER ROLE ... PASSWORD`) and give each service its own login in its database
setting, `OPS_DATABASE_URL_<SERVICE>`. On Azure the server admin is not a superuser: run `GRANT ops_migrator TO
<admin>` first, and add `vector` to the server's `azure.extensions`.

| File | What it holds |
|---|---|
| `roles.sql` | Every role below, each guarded so it can run again |
| `bundle.sql` | The whole schema in dependency order: tables, constraints, indexes, row-level security and its policies |
| `grants.sql` | Each service login's rights; run it after every install and upgrade |
| One file per service | The same objects split by service, for review. Apply the bundle, not these |
| `manifest.json`, `SHA256SUMS` | The release, each service's schema version, and every file's checksum |

## The logins

| Role | Rights |
|---|---|
| `ops_migrator` | Owns every table, index and policy. Not a superuser; cannot create roles or databases |
| `ops_<service>_runtime`, one per service | Logs in; reads and writes its own service's tables only. Cannot create or drop a table. Row-level security applies to it |
| `ops_runtime_tenant`, `ops_runtime_system` and two platform roles | No login. The services switch to them inside a transaction; only the background loops use `ops_runtime_system`, which reads across tenants |

## Upgrade

An upgrade comes as `upgrade-roles.sql`, `upgrade.sql` and `downgrade.sql` from the running release to the new one. In
DBA mode, `./install.sh upgrade` writes them to `./dba/upgrade-<from>-to-<to>/` and waits for you.

```bash
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -f upgrade-roles.sql
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f upgrade.sql
psql -v ON_ERROR_STOP=1 "postgresql://ops_migrator@<host>/ops" -f grants.sql     # the new release's
```

Each step checks the version it starts from and stops before any change when the database is elsewhere. Stop the
services before you run it, and start only the new release after it: some steps move rows the old release still
writes. [Upgrade](upgrade.md) has the whole sequence and the roll back.

## Check a running database

Every service reads the schema version at start and refuses to run on one it does not match:

```text
SchemaBehindError: models-service: the database's schema is behind: it records models_0005, this build needs models_0006. Apply the upgrade first.
```

To list every object that is missing, extra or changed against what the release expects, run the drift check from a
clone at the release tag; it needs a throwaway PostgreSQL server it may create scratch databases on.

```bash
make db-drift DATABASE=<live database URL> SERVER=<throwaway server URL>
```

## SQL Server and Azure SQL

SQL Server 2025 and Azure SQL Database are partial. Continuous integration runs the store, service kit and identity
suites, and each service's store tests, on SQL Server 2025 beside PostgreSQL on every change. A full install of Ops AI
on SQL Server is not yet proven; install on PostgreSQL for now. What is ready and what is still to come is in
[Azure SQL](../guide/azure-sql.md).

The SQL Server scripts are `sqlcmd` scripts; run each with `-b`, which stops at the first error.

```bash
sqlcmd -b -d master -i roles.sql -v database=ops ops_migrator_password=<...> ops_agents_runtime_password=<...>
sqlcmd -b -U ops_migrator -d ops -i bundle.sql
sqlcmd -b -U ops_migrator -d ops -i grants.sql
```

## Limits

- Upgrades by DBA script start at 1.0.0. A database from a dated release before 1.0.0 is upgraded by the schema job.
- The drift check runs from a source clone; a packaged command is planned. On SQL Server it is planned.
- Signing in to the database with Microsoft Entra ID or a managed identity is planned; the scripts use SQL logins.
