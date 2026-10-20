# Database scripts

The schema as scripts a DBA reviews and applies, generated from the migration chains: the baseline (roles, one file
per service, the bundle, grants), guarded upgrade and downgrade SQL between two refs, and a drift check. Runbook:
`docs/deploy/database.md`.

| File | Role |
|---|---|
| `schema.py` | `ddl`, `upgrade-sql`, `drift`, `diff`, `install` (trials only); `make db-ddl`, `db-upgrade-sql`, `db-drift`, `db-release` |
| `postgres.py` | The PostgreSQL dialect: scratch databases, dumps, the restore that makes comparisons fair, guards, roles and grants |
| `mssql.py` | The SQL Server dialect: compiles the baseline from the store models (no server), security policies, logins and grants, and upgrades from Alembic's offline SQL after each chain's SQL Server baseline |
| `golden/mssql/` | The reviewed SQL Server DDL per chain, plus roles.sql and grants.sql; `make db-ddl-golden` rewrites it after a model change |
| `chain_tables.py` | The tables a service's code declares, read from its migrations' env |
| `proof.sh` | The proof on a throwaway PostgreSQL: baseline equals Alembic, upgrade equals head, runtime roles refused DDL, drift red and green, a service refusing an old schema |
| `tests/test_offline.py` | Every revision after the eight named renders as offline SQL (run by `make verify`) |
| `tests/test_mssql_ddl.py` | The golden files equal what the models compile to; a policy on every TENANT_SCOPED table and no other; nullable unique keys filtered; upgrades before the baseline refused (run by `make verify`) |
