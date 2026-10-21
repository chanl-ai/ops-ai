# Workspace admins create, rename, archive and restore teams

Status: current. Id: `uc-164`. Service: `platform-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; the ui layer runs with `ISOLATED=1` |

The script starts platform-service in dev on the run's database with the dev seed: Wanjiru Kamau, the workspace admin
(Admin in every team, `*`), team `team_ops` (Priya Shah admin, Ravi Menon viewer) and `team_security` (Sam Adeyemi
admin); demo password `northfield-demo`. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya, admin of team_ops only, and Sam, admin of the Security team only, create a team | 403 each |
| 2 | Wanjiru creates Lending with Ravi as its first admin | 201; Ravi's next token holds Lending as admin; a second "LENDING" is 409 |
| 3 | She renames it Retail Lending | Ravi's team list shows the new name |
| 4 | She archives it | Ravi's next token drops it; an invitation into it is refused; the Security team cannot be archived |
| 5 | She restores it | Back in Ravi's next token; the workspace list shows it with 1 member and 1 admin |
| ui | Wanjiru opens Access, then Teams, creates a team with its first admin and archives it; James opens Teams | She sees the list and every control; James sees that workspace admins manage teams and no control |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-164-api.py` | passing |
| ui | `platform-service/scripts/test-uc-164-ui.mjs` | passing |

## Non-vacuous check

`Ravi's next token no longer carries it`: with the token claims reading archived teams, the archived team stays in his
token and the check fails.
