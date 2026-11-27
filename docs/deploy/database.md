# Database

Status: current for PostgreSQL, proven on a throwaway server. SQL Server 2025 and Azure SQL are partial: see
[SQL Server and Azure SQL](#sql-server-and-azure-sql).

A production database is normally changed by a DBA, from reviewed scripts, in a change window. Software that creates
its own tables with a powerful login at start-up does not fit that process. Ops AI supports the DBA's way. Every script
is generated from the release and is never edited by hand. Each service runs on its own login, which cannot change the
schema. This page covers installing, upgrading and checking the database on PostgreSQL.

## Choose who applies the schema

| Mode | Who applies it | Use it when |
|---|---|---|
| Automatic | The install's schema job, with a superuser login you give it | A trial, or a database Ops AI owns |
| DBA | Your DBA, from the release's scripts | Production: the services never hold a login that may change the schema |

The [install script](install.md) asks which one you want (`--db-mode auto` or `--db-mode dba`). In DBA mode it writes the
scripts to `./dba/` and prints the three `psql` commands to run, then waits until the schema is current. The scripts
also come from two other places.

| Source | How to get the scripts |
|---|---|
| The release image | `id=$(docker create ghcr.io/chanl-ai/ops-ai/db-scripts:1.2.0 none)`, then `docker cp "$id:/db/postgres" ./postgres` |
| A [release package](release-package.md) | The folder `db/postgres/` |

## Install on PostgreSQL

You need PostgreSQL 15 or newer, or Azure Database for PostgreSQL Flexible Server 16 or newer. The `vector` extension
must be available, because knowledge search stores its vectors in it. No other extension is needed.

Run the commands from the folder that holds the scripts. Replace `<admin>` and `<host>` with your server admin and
address. Replace `ops` with another database name if you prefer.

```bash
shasum -a 256 -c SHA256SUMS
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/postgres" -f roles.sql
# Give every runtime login a password, one ALTER ROLE for each of the seven services:
psql "postgresql://<admin>@<host>/postgres" -c "ALTER ROLE ops_agents_runtime PASSWORD '<password>'"
psql "postgresql://<admin>@<host>/postgres" -c "GRANT ops_migrator TO CURRENT_USER" -c "CREATE DATABASE ops OWNER ops_migrator"
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "CREATE EXTENSION IF NOT EXISTS vector" \
  -c "SET ROLE ops_migrator" -f bundle.sql
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "SET ROLE ops_migrator" -f grants.sql
```

The services are `platform`, `agents`, `tools`, `models`, `kb`, `files` and `documents`, so the login names run from
`ops_platform_runtime` to `ops_documents_runtime`. Give each service its own login in its own database setting,
`OPS_DATABASE_URL_<SERVICE>`, in the form `postgresql+asyncpg://ops_agents_runtime:<password>@<host>:5432/ops`. Add
`?ssl=require` for a server that requires TLS.

On Azure Database for PostgreSQL the server admin is not a superuser. Add `vector` to the server's `azure.extensions`
before you create it, and keep the `GRANT ops_migrator TO CURRENT_USER` line, which lets the admin run the bundle as the
schema owner.

| File | What it holds |
|---|---|
| `roles.sql` | Every role listed below, each guarded so the script can run again |
| `bundle.sql` | The whole schema in dependency order: tables, constraints, indexes, row-level security and its policies |
| `grants.sql` | Each service login's rights. Run it after every install and every upgrade |
| One file per service | The same objects split by service, for review. Apply the bundle, not these |
| `manifest.json`, `SHA256SUMS` | The release, each service's schema version, and every file's checksum |

## The logins

| Role | Rights |
|---|---|
| `ops_migrator` | Owns every table, index and policy. It is not a superuser and cannot create roles or databases |
| `ops_<service>_runtime`, one per service | Logs in, and reads and writes its own service's tables only. It cannot create or drop a table, and row-level security applies to it |
| `ops_runtime_tenant`, `ops_runtime_system`, `ops_platform_tenant` and `ops_platform_lookup` | No login. The services switch to them inside a transaction. Only the background loops use `ops_runtime_system`, which reads across tenants |

## Upgrade

Two kinds of script move a database to a new release. Both check the version they start from and stop before any change
when the database is somewhere else.

**With the install script in DBA mode,** `./install.sh upgrade` writes one SQL file for each service that needs one to
`./dba/upgrade-<from>-to-<to>/`, named `01-` onwards in the order to run them. It prints the `psql` command for each,
then for `dba/postgres/grants.sql`, and waits until the schema is current. Your DBA runs each file as `ops_migrator`, in
order.

**From a clone,** the guarded scripts of the release pair come from `make db-upgrade-sql FROM=<old tag> TO=<new tag>
OUT=<folder>`. The folder holds `upgrade-roles.sql`, `upgrade.sql` and `downgrade.sql`.

```bash
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -f upgrade-roles.sql
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "SET ROLE ops_migrator" -f upgrade.sql
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "SET ROLE ops_migrator" -f grants.sql  # the new release's
```

Stop the services before you run the scripts, and start only the new release afterwards, because some steps move rows
the old release still writes. [Upgrade](upgrade.md) has the whole sequence and the rollback.

## Check a running database

Every service reads the schema version at start and refuses to run on one it does not match. The error names the
upgrade that is missing:

```text
SchemaBehindError: models-service: the database's schema is behind: it records models_0005, this build needs models_0006. Apply the upgrade first.
```

To list every object that is missing, extra or changed against what the release expects, run the drift check from a
clone at the release tag. It needs a throwaway PostgreSQL server where it may create scratch databases. Do not point it
at a server you use for anything else.

```bash
make db-drift DATABASE=<live database URL> SERVER=<throwaway server URL>
```

## SQL Server and Azure SQL

SQL Server 2025 and Azure SQL Database are partial. On every change, continuous integration runs the store, service kit
and identity suites, and each service's store tests, on SQL Server 2025 beside PostgreSQL. A full install of Ops AI on
SQL Server has not been proven, so install on PostgreSQL for now. [Azure SQL](../guide/azure-sql.md) lists what is ready
for review and what is still to come.

The SQL Server scripts are `sqlcmd` scripts. Run each with `-b`, which stops at the first error, and with `-I`, which
turns on quoted identifiers. Without `-I`, SQL Server refuses the bundle's filtered indexes. `roles.sql` takes one
password variable for `ops_migrator` and one for each of the seven runtime logins.

```bash
sqlcmd -S <server> -U <admin> -b -I -d master -i roles.sql -v database=ops ops_migrator_password=<...> \
  ops_platform_runtime_password=<...> ops_agents_runtime_password=<...> ops_tools_runtime_password=<...> \
  ops_models_runtime_password=<...> ops_kb_runtime_password=<...> ops_files_runtime_password=<...> \
  ops_documents_runtime_password=<...>
sqlcmd -S <server> -U ops_migrator -b -I -d ops -i bundle.sql
sqlcmd -S <server> -U ops_migrator -b -I -d ops -i grants.sql
```

## Limits

- Upgrades by DBA script start at version 1.0.0. A database from a dated release before 1.0.0 is upgraded by the schema
  job, not by script.
- The drift check runs from a source clone, and a packaged command is planned. It does not run against SQL Server.
- Signing in to the database with Microsoft Entra ID or a managed identity is planned. The scripts use SQL logins.
