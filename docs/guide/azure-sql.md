# Azure SQL

Status: partial. Read from the release's SQL Server scripts, their tests and the continuous integration jobs.

If your organisation runs SQL Server or Azure SQL and does not run PostgreSQL, you need to know now whether Ops AI can
use it. Today it cannot run on either. This page says how far the work has got, so your DBA can review the schema in
parallel with the rest.

> [!WARNING]
> A full install of Ops AI on Azure SQL Database or SQL Server has not been proven. Install on PostgreSQL today. Azure
> Database for PostgreSQL Flexible Server is supported. The SQL Server scripts are ready for your DBA to review now, so
> the review can run in parallel with the remaining work.

Azure SQL Database and SQL Server 2025 are the second database Ops AI is built for. Each service reaches the database
only through its own store. The places where the two databases differ sit in one shared layer: locking, queue claims,
inserts that update an existing row, the clock, and the tenant of a transaction. The services above the stores do not
change. On every change, continuous integration runs the store, service kit and identity suites, and each service's
store and isolation tests, on SQL Server 2025 beside PostgreSQL, and it fails when a SQL Server case is skipped.

Ops AI's own test machine has also applied the SQL Server scripts to a SQL Server 2025 instance with `sqlcmd`, the way a
DBA would, and compared the result with the store models and the tenant policies. That check runs from a source clone
and is not part of a release.

## Ready for review

| Item | What it holds | Status |
|---|---|---|
| `roles.sql` | Run in `master` as a server administrator: one SQL login per service plus the schema owner `ops_migrator`, each password a sqlcmd variable; the database with collation `Latin1_General_100_BIN2_UTF8` and `READ_COMMITTED_SNAPSHOT ON`, owned by `ops_migrator` | Built |
| One script per service, and `bundle.sql` | Every table, index, key and default, the version table stamped at the release, and a security policy per tenant table. The bundle refuses a database with another collation, without read-committed snapshot, or below compatibility level 160 | Built |
| `grants.sql` | A database user per service login with SELECT, INSERT, UPDATE and DELETE on its own tables and nothing else; the one system user the background loops switch to, which only the agents login may impersonate, with the same narrow grants as on PostgreSQL | Built |
| `manifest.json` and `SHA256SUMS` | The commit, each service's schema version, every file's checksum | Built |
| Tenant isolation | A security policy on each tenant table of the agents and platform services: a filter predicate on reads and block predicates after insert and after update, reading the tenant from `SESSION_CONTEXT`, which the services set and clear per transaction | Built in the scripts |
| Data types | Text as `VARCHAR(max)` under the UTF-8 collation, JSON as `NVARCHAR(max)`, timestamps as `DATETIMEOFFSET`, booleans as `BIT`, keys named as on PostgreSQL so later upgrades name the same objects | Built |
| Upgrade scripts | Generated per release pair the same way as for PostgreSQL, each step guarded by the version it starts from | Built |
| How the scripts are kept right | Compiled from each service's table definitions, which tests hold equal to what the PostgreSQL migrations build, and compared on every change with reviewed copies | Built |

Your DBA runs them with `sqlcmd -b -I`. The `-b` option stops at the first error. The `-I` option turns on quoted
identifiers, which the bundle's filtered indexes need, because `sqlcmd` leaves them off. `roles.sql` takes a password
variable for `ops_migrator` and one for each of the seven runtime logins (`ops_platform_runtime`, `ops_agents_runtime`,
`ops_tools_runtime`, `ops_models_runtime`, `ops_kb_runtime`, `ops_files_runtime` and `ops_documents_runtime`).

```bash
sqlcmd -S <server> -U <admin> -b -I -d master -i roles.sql -v database=ops ops_migrator_password=<...> \
  ops_platform_runtime_password=<...> ops_agents_runtime_password=<...> ops_tools_runtime_password=<...> \
  ops_models_runtime_password=<...> ops_kb_runtime_password=<...> ops_files_runtime_password=<...> \
  ops_documents_runtime_password=<...>
sqlcmd -S <server> -U ops_migrator -b -I -d ops -i bundle.sql
sqlcmd -S <server> -U ops_migrator -b -I -d ops -i grants.sql
```

What a DBA should expect to see after these three scripts is the schema, the logins and the tenant policies, and nothing
else: the services do not run on it yet.

## Still to come

| Item | Why it matters | Status |
|---|---|---|
| A full install on Azure SQL or SQL Server, from the scripts to a signed-in console | The scripts and each service's stores are tested on SQL Server 2025; the whole install has not run on one | Planned |
| Running the services on Azure SQL and SQL Server | Each service's store and isolation tests pass on SQL Server 2025; database code specific to PostgreSQL remains in some services and is moving into the shared layer | Partial |
| Knowledge search | PostgreSQL full-text search and pgvector have no SQL Server equivalent in the scripts yet; a search there returns no passages | Planned |
| Sign-in data | The platform service still sets the tenant with PostgreSQL statements and uses four lookup functions that run before the tenant is known | Planned |
| The worker's queue claim and the timer poller | The claim happens before the tenant is known, which SQL Server's block predicate refuses; the timer poller starts only on PostgreSQL | Planned |
| Tenant policies for the tools, models, knowledge, files and documents tables | The same gap as on PostgreSQL ([Tenants and teams](data-and-database.md#tenants-and-teams)) | Planned |
| Signing in to the database with Microsoft Entra ID or a managed identity | The scripts use SQL logins | Planned |
| A drift check against a live SQL Server | The packaged check (`make db-drift`) works for PostgreSQL only. On SQL Server the comparison runs from the test image | Planned |
