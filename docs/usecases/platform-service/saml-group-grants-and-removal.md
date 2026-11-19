# Leaving a group at the company's identity provider ends only what that group gave

Status: current. Id: `uc-711`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (Wanjiru Kamau, the workspace admin,
Admin and Security admin in every team) and the local fake identity provider. No real identity provider and no model
is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru sets a SAML provider that maps `platform-readers` to team_platform as viewer and `platform-builders` to team_platform as builder | 200; `groups.onMissing` is `remove`, the default for a new provider |
| 2 | Ana, new, signs in carrying both groups, then connects an assistant to each team's MCP address | team_ops as chat user (her first sign-in) and team_platform as builder, the higher of the two roles; two assistant connections |
| 3 | Ana signs in and the provider sends Entra's overage claim in place of her groups | Nothing changes: team_platform stays builder |
| 4 | Ana signs in carrying neither group | team_platform ends (audited `member.group_removed`); team_ops, from her first sign-in, stays |
| 5 | Ana's assistants try to renew | the team_platform one is refused (`invalid_grant`); the team_ops one renews |
| 6 | Wanjiru reads the audit in team_platform for `oauth.grant_ended` | one row, ended "by group", for the team_platform connection only |

A membership given by hand is never removed by a sign-in; the service tests cover it
(`services/platform-service/tests/test_saml_groups.py`). A missing groups attribute and a present but empty one both
mean no groups and end what groups gave, as when Keycloak drops the attribute for a person in no group; only Entra's
overage claim leaves memberships as they are.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-711-api.py` | passing |

In the console: the group rules are edited in the Add SAML provider wizard's third step (in progress); this use case
stays at the api layer until it ships.

## Non-vacuous check

`after she leaves both groups, team_platform ends`: with the removal in `_join_groups` skipped, team_platform stays and
the check fails. Likewise `the audit names that one assistant connection as ended by group` and the renewal check
fail while the group removal leaves the team's assistant connections live and unaudited.
