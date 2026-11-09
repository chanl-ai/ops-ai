---
name: ops-database
description: Point Ops AI at another database: our container, an existing PostgreSQL 15 to 17 (Azure Database for PostgreSQL among them), and later Azure SQL. Use when someone asks which database Ops AI needs or how to use their own.
agent: agent
---

# ops-database: switch the database

<!-- Generated from `docs/guide/skills/ops-database.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make setup, make migrate, make reset-db.

## When to use it

A person wants their own PostgreSQL instead of the container, or asks about Azure SQL.

## Steps

1. `make setup` with `DATABASE=postgresql://user:password@host:5432/db` connects, checks the version (15 to 17) and
   that every tenant table it already holds has its row policy on; an empty database passes. It writes
   `OPS_DATABASE_URL` only when it passed, and never prints the password.
2. `make migrate` applies every service's chain to the new database; `make up` then runs on it.
3. `make reset-db` wipes the stack's own database and rebuilds it; it asks first, since every checkout on the machine shares it.
4. `make db-move-image` moves a stack started on the old `postgres:17-alpine` image onto `pgvector/pgvector:pg17`, which meaning search needs: it dumps every database, starts the new image on a new volume (`ops-runtime-pgvector`) and restores. Until it runs, a recreated postgres container starts empty on the new volume; the old volume `ops-runtime-pg` is kept.
4. Azure SQL is listed and refused as not supported in this version until the store runs on it;
   `docs/guide/azure-sql.md` has the plan.

## Proof

```bash proof
SETUP_FILE=/tmp/ops-database.env make setup ANSWERS=scripts/setup/answers.qa.env
make migrate
```
