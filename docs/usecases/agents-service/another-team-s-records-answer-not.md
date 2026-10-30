# Another team's records answer not found

Status: current. Id: `uc-526`. Service: `agents-service`. Layers: api, ui (ui layer an earlier change).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Priya, in Operations, opens her case, workflow and run and sees each | ui | 3 | 3 |
| S2 | Sam, in Security, opens the same addresses and each page says not found | ui | 4 | 4 |
| S3 | No not-found page names Operations or team_ops | ui | 5 | 5 |

A team is the workspace (docs/architecture/identity-and-tenancy.md, "The team is the workspace"): a record of another
team is not found, and the answer names no team. This use case walks the records a person reaches by id in
agents-service.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The dev seed's people | platform-service's seed: Priya Shah (Operations admin), Sam Adeyemi (Security admin) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya and Sam sign in through platform-service | Both 200 |
| 2 | Priya, acting in Operations, makes a task type (a copy of Write approval), a case type (a copy of Complaint), a case, a workflow, puts the workflow live and starts a run | Each made |
| 3 | Priya reads each record | 200 |
| 4 | Sam, acting in Security, reads each record by its id | 404 for each |
| 5 | Sam's answers | Name neither `team_ops` nor Operations |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-526-api.py` | passing |
| ui | `agents-service/scripts/test-uc-526-ui.mjs` | passing: the case, workflow and run pages, as Priya and as Sam |

## Non-vacuous check

Each 404 is paired with Priya's 200 for the same id, so a record that was never made cannot pass as hidden. The
database's half is shown failing in the isolation suites: with one table's policy dropped, the suite names that table
(`tests/store/test_team_tables_isolation.py`, `services/kb-service/tests/test_kb_isolation.py`, run 2026-10-22).
Knowledge bases and document types join this walk with an earlier change, when the dev header caller stops reading every team at
the request level.
