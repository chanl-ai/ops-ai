# A workspace sets its security and default teams, and SSO groups map people to teams

Status: current. Id: `uc-212`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (Wanjiru Kamau, the workspace admin,
Admin and Security admin in every team; Priya Shah admin of team_ops; Sam Adeyemi admin of team_security), sign-in
URLs, an OIDC client secret named `uc-oidc`, and the local fake identity provider. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya sets the workspace's teams | 403 |
| 2 | Wanjiru creates Lobby, then makes team_ops the security team and Lobby the default team | 200; Priya now holds Security admin in team_ops, Sam no longer in team_security; `/v1/me` names team_ops |
| 3 | Wanjiru sets an OIDC provider whose first sign-in names a role and no team, mapping group `fraud-analysts` to team_fraud as viewer | 200 |
| 4 | A new person carrying `fraud-analysts` signs in; another without it | The first lands in Lobby as chat user and team_fraud as viewer; the second in Lobby only |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-212-api.py` | passing |

## Non-vacuous check

`Sam no longer holds it in team_security`: with the re-mirroring removed, Sam keeps Security admin and the check fails.
