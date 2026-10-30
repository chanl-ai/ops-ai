# Agents starts and a chat turn saves its checkpoint

Status: current. Id: `uc-566`. Service: `agents-service`. Layers: api.

A person chats with an agent on an install on either database, PostgreSQL or SQL Server, and the conversation keeps its
state between turns: agents starts, the reply comes back, the turn's checkpoint is saved in the person's team and in no
other team of the tenant, and a reload shows the conversation.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A person's chat turn on PostgreSQL saves its checkpoint in the person's team only | api | 1 to 5 | 4 |
| S2 | The same on a SQL Server install made from the reviewed scripts | api | 1 to 5 | 4 |

## Preconditions

| Needs | How |
|---|---|
| S1: the use-case PostgreSQL database | The harness creates and migrates it (`OPS_USECASE_DB`) |
| S2: the SQL Server test machine, a runner beside it and the HEAD bundle | `make uc-sql-server`, which installs the bundle on a scratch database and runs this script with it (`docs/deploy/fly.md`, SQL Server test machine) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start agents-service on the scripted model against the database | It answers its health check |
| 2 | Start a chat with `ag_branch` in `team_all` | 201 |
| 3 | Send one message | The stream starts with `start` and ends with `done` |
| 4 | Read the thread's checkpoints under the tables' security policy, as `team_all` and as another team of the tenant | At least one for `team_all`; none for the other team |
| 5 | Reload the thread | The user's message, then the reply |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-566-api.py` (no argument: PostgreSQL; the HEAD bundle's folder: SQL Server) | passing on PostgreSQL; passing on SQL Server 2025 run from the test image through `fly proxy`; on the runner machine (`make uc-sql-server`) the walk does not finish, cause open |

## Non-vacuous check

Watched red on PostgreSQL before an earlier change T004: steps 1 to 3 and 5 pass, and step 4 finds no checkpoint in `team_all`,
since the saver writes every chat's checkpoints under one fixed team (three rows under `local`). Watched red on
SQL Server the same day: agents stops at start, since the checkpointer opens an asyncpg pool and asyncpg refuses an
`mssql+aioodbc` URL. On SQL Server the script serves a knowledge service that knows no knowledge base in place of
kb-service, which does not run on SQL Server yet nor on the runner; `ag_branch`'s chat names none.
