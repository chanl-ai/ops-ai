# A SQL Server install migrates agents to the head

Status: current. Id: `uc-565`. Service: `agents-service`. Layers: api.

A bank's DBA installs Ops AI on SQL Server from the reviewed scripts, or upgrades an earlier SQL Server install, and
ends with the schema the code expects: every chain at its head, the tables a chat saves its state in, the memory
search index, and a tenant policy on every tenant-scoped table.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A DBA installs the latest release on an empty SQL Server database and it matches the code | api | 1, 2 | 2 |
| S2 | A DBA upgrades an install of an earlier release to the latest and it matches the code | api | 3, 4, 5 | 5 |

S2 waits. SQL Server upgrades start from the first release whose bundle installs, the release cut after an earlier change, because
no SQL Server install of an earlier release exists. Until a migration lands after that release, the walk runs S1 only
and prints `WAIT 3-5` in place of S2's checks.

## Preconditions

| Needs | How |
|---|---|
| The SQL Server test machine and a runner beside it | `make uc-sql-server`, which starts both, runs this script and stops both (`docs/deploy/fly.md`, SQL Server test machine) |
| The HEAD bundle | Built by the same target: `make db-ddl DIALECT=mssql` at HEAD |
| For S2: an earlier release's bundle and the upgrade SQL from it | The same target with `SQL_SERVER_BASE_REF=<release>`: `make db-ddl DIALECT=mssql` at that release, `make db-upgrade-sql DIALECT=mssql FROM=<release>` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Install the HEAD bundle (roles, bundle, grants) on an empty database | sqlcmd finishes without an error |
| 2 | Read the database | Every chain's version row is its head; the checkpointer's three tables are there; `agent_memories` has its full-text index where Full-Text Search is installed; no drift from the store models and their tenant policies |
| 3 | Install the earlier release's bundle on another empty database | sqlcmd finishes without an error |
| 4 | Apply the upgrade SQL, then HEAD's grants | Every step runs; none is refused |
| 5 | Read the database | As step 2 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-565-api.py` | S1 passing on SQL Server 2025; S2 waiting for an earlier installable release |

## Non-vacuous check

S1 was watched red on the real server before an earlier change: the bundle had no checkpointer tables and no memory full-text
index, refused `ON DELETE RESTRICT`, and declared foreign keys in an order that did not match their target key. S2 has
not been seen red, since it cannot run yet; its first run needs the same check.
