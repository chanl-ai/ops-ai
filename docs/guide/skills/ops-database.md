# ops-database: switch the database

Status: current. Proven by `make skills-proof`.

skill: ops-database
description: Point Ops AI at another database: our container, an existing PostgreSQL 15 to 17 (Azure Database for PostgreSQL among them), and later Azure SQL. Use when someone asks which database Ops AI needs or how to use their own.
targets: make setup, make migrate, make reset-db

## When to use it

A person wants their own PostgreSQL instead of the container, or asks about Azure SQL.

## Steps

1. `make setup` with `DATABASE=postgresql://user:password@host:5432/db` connects, checks the version (15 to 17) and
   that every tenant table it already holds has its row policy on; an empty database passes. It writes
   `OPS_DATABASE_URL` only when it passed, and never prints the password.
2. `make migrate` applies every service's chain to the new database; `make up` then runs on it.
3. `make reset-db` wipes the stack's own database and rebuilds it; it asks first on the shared stack.
4. Azure SQL is listed and refused as not supported in this version until the store runs on it;
   `docs/guide/azure-sql.md` has the plan.

## Proof

```bash proof
SETUP_FILE=/tmp/ops-database.env make setup ANSWERS=scripts/setup/answers.qa.env
make migrate
```
