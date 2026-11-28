# Database scripts: working rules

Status: current.

`deploy/database/` generates the schema as scripts a DBA reviews and applies: the baseline per service, the SQL Server
dialect (`mssql.py`), guarded upgrade and downgrade SQL between two refs, the reviewed golden DDL and the drift check.
It owns no table: models and migrations live with each service and `packages/ops_store`. Overview:
[README.md](README.md); runbook: [docs/deploy/database.md](../../docs/deploy/database.md); folder rules for the
rest of `deploy/`: [deploy/CLAUDE.md](../CLAUDE.md).

## Known traps

- A migration that adds a tenant-scoped table => create its row policy after the table and drop it before the table on downgrade; the policy names the table, so neither order works the other way round, and `make db-ddl-golden` (reviewed) records it
- A model or migration change => run `make db-ddl-golden`, review the diff, and run `uv run pytest -q deploy/database/tests`; the golden files fail on a revision SQL Server cannot render
- A migration with batched fills or backfills => `upgrade.sql` runs them as the migrator, outside one wrapping transaction; prove it with `make db-scripts-proof FROM=<last tag>`
- A new system user or a table it reads => add both to `SYSTEM_USERS`, which renders the grants
- A store change tested only with `make ci-local` => it skips `store-mssql`; use `deploy/database/mssql_remote.sh up`, then `test <member> -q <tests>`, and never `down` or `sweep` on the shared server

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [data access](../../docs/architecture/standards/data-access.md) (`DA1` to `DA13`), [tenant isolation and access](../../docs/architecture/standards/tenancy-and-access.md) (`TN1` to `TN5`, `AC1` to `AC5`), [delivery, deploy and upgrade](../../docs/architecture/standards/delivery.md) (`DL1` to `DL9`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
