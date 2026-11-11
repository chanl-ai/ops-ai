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
| 2 | Ana, new, signs in carrying both groups | team_ops as chat user (her first sign-in) and team_platform as builder, the higher of the two roles |
| 3 | Ana signs in and the provider sends Entra's overage claim in place of her groups | Nothing changes: team_platform stays builder |
| 4 | Ana signs in carrying neither group | team_platform ends (audited `member.group_removed`); team_ops, from her first sign-in, stays |

A membership given by hand is never removed by a sign-in; the service tests cover it
(`services/platform-service/tests/test_saml_groups.py`). A missing groups attribute and a present but empty one also
remove nothing, since neither says which groups the person left.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-711-api.py` | passing |

In the console: the group rules are edited in the Add SAML provider wizard's third step (in progress); this use case
stays at the api layer until it ships.

## Non-vacuous check

`after she leaves both groups, team_platform ends`: with the removal in `_join_groups` skipped, team_platform stays and
the check fails.
