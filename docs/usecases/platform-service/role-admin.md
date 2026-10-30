# A person invited as an admin runs their team's people, and only their team's

Status: current. Id: `uc-219`. Service: `platform-service`, agents-service, console. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; run the ui layer with `ISOLATED=1` |

platform-service runs with the dev seed's own roles (`OPS_SEED_EVERYONE_ADMIN` off) and agents-service verifies its
tokens. The person checked is never a seeded one: an admin invites them through the product and they accept with a
password. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites a new address as admin | They join team_ops as admin |
| 2 | The admin invites a person as viewer (ui: from Access), who accepts | They join as viewer |
| 3 | The admin makes them a builder (ui: Change role) | Their next token carries builder |
| 4 | The admin removes them | Their next token carries no team_ops |
| 5 | The admin invites into team_fraud | 403 |
| 6 | The admin removes Priya, then demotes themselves | Priya removed; their own demotion skipped `last_admin` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-219-api.py` | passing |
| ui | `platform-service/scripts/test-uc-219-ui.mjs` | passing |

## Non-vacuous check

Inviting uc-216's person as admin instead of viewer fails six of its checks.
