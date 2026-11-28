# Database

Status: current for PostgreSQL.

In most organisations, your DBA changes a production database from reviewed scripts during a change window. Software
that creates its own tables at start-up with a powerful login does not fit that process, so Ops AI is built to work with
it. Each script is generated from the release and checked against its checksums, so nobody needs to edit one by hand.
Once the schema is in place, each service runs on its own login, and that login cannot change the schema. This page
covers installing, upgrading and checking the database on PostgreSQL. These steps have been proven on a throwaway
server. SQL Server 2025 and Azure SQL are partial: see [SQL Server and Azure SQL](#sql-server-and-azure-sql).

## Choose who applies the schema

| Mode | Who applies it | Use it when |
|---|---|---|
| Automatic | The install's schema job, with a superuser login you give it | A trial, or a database Ops AI owns |
| DBA | Your DBA, from the release's scripts | Production: the services never hold a login that may change the schema |

The [install script](install.md) asks which one you want (`--db-mode auto` or `--db-mode dba`). In DBA mode the two of
you work in this order. The script's own `1-server.sql` takes the place of the `roles.sql` and `ALTER ROLE` steps below.
The scripts also come from two other places.

<!-- site: sequence caption="DBA mode: the script writes the scripts and waits, your DBA applies them, and the services start only on a current schema" -->
1. **Install script → Your DBA**: Writes the scripts and each login's password to `./dba/` and prints three `psql` commands
2. **Your DBA → PostgreSQL**: Runs `1-server.sql` for the roles and the database, then the bundle and the grants
3. **Install script → PostgreSQL**: Checks the schema version and waits until it is current
4. **Install script → Services**: Starts them, each on its own login

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
# Give every runtime login a password, once for each of the seven services:
for s in platform agents tools models kb files documents; do
  psql "postgresql://<admin>@<host>/postgres" -c "ALTER ROLE ops_${s}_runtime PASSWORD '<password for $s>'"
done
psql "postgresql://<admin>@<host>/postgres" -c "GRANT ops_migrator TO CURRENT_USER" -c "CREATE DATABASE ops OWNER ops_migrator"
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "CREATE EXTENSION IF NOT EXISTS vector" \
  -c "SET ROLE ops_migrator" -f bundle.sql
psql -v ON_ERROR_STOP=1 "postgresql://<admin>@<host>/ops" -c "SET ROLE ops_migrator" -f grants.sql
```

Keep the seven passwords, because they go into the services' database settings. The login names run from
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
| One file per service | The same objects split by service, for review only. Apply the bundle instead |
| `manifest.json`, `SHA256SUMS` | The release, each service's schema version, and every file's checksum |

## The logins

| Role | Rights |
|---|---|
| `ops_migrator` | Owns every table, index and policy. It is not a superuser and cannot create roles or databases |
| `ops_<service>_runtime`, one per service | Logs in, and reads and writes its own service's tables only. It cannot create or drop a table, and row-level security applies to it |
| `ops_runtime_tenant`, `ops_runtime_system`, `ops_platform_tenant` and `ops_platform_lookup` | No login. The services switch to them inside a transaction. Only the background loops use `ops_runtime_system`, which reads across tenants |

## Upgrade

You can move a database to a new release with either of two kinds of script. Both check the version the database is at
before they start, and both stop before making any change if it is not the version they expect.

If you installed with the script in DBA mode, `./install.sh upgrade` writes one SQL file for each service that needs one
to `./dba/upgrade-<from>-to-<to>/`. The files are numbered from `01-` in the order to run them. The script prints the
`psql` command for each file and then for `dba/postgres/grants.sql`, and waits until the schema is current. Your DBA runs
each file as `ops_migrator`, in order.

If you work from a clone, `make db-upgrade-sql FROM=<old tag> TO=<new tag> OUT=<folder>` writes the guarded scripts for
that pair of releases. The folder holds `upgrade-roles.sql`, `upgrade.sql` and `downgrade.sql`.

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

Support for SQL Server 2025 and Azure SQL Database is partial. On every change, continuous integration runs the store, service kit
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

- The upgrade scripts refuse a step that crosses a data change that cannot be written as SQL, and they name it. For a
  database that far behind, upgrade through the schema job.
- The drift check runs from a source clone, and a packaged command is planned. It does not run against SQL Server.
- Signing in to the database with Microsoft Entra ID or a managed identity is planned. The scripts use SQL logins.
