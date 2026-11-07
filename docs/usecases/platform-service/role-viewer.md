# A person invited as a viewer reads the team's work and changes none of it

Status: current. Id: `uc-216`. Service: `platform-service`, agents-service, console. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

platform-service runs with the dev seed's own roles (`OPS_SEED_EVERYONE_ADMIN` off) and agents-service verifies its
tokens. The person checked is never a seeded one: an admin invites them through the product and they accept with a
password. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya, admin of team_ops, invites a new address as viewer; the person accepts with a password | Their token names team_ops as viewer |
| 2 | They list the team's agents | 200 |
| 3 | They create, edit, ask to publish and delete an agent | 403 each |
| 4 | They invite someone | 403 |
| 5 | They act in team_fraud | 403 `team_forbidden` |
| 6 | ui: they open an agent page and Access | View only, no Save and no Test; no Invite |
| 7 | ui: they open Channels and Chat embed; James, a builder, opens the same pages | The viewer sees no Connect channel, no Connect or Manage on a kind's card and no Embed on a page; James sees each |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-216-api.py` | passing |
| ui | `platform-service/scripts/test-uc-216-ui.mjs` | passing |

## Non-vacuous check

Inviting uc-216's person as admin instead of viewer fails six of its checks. With the Channels and agent Test gates taken out of the console, the ui layer fails its Test and Channels checks
(a Test tab, and Connect channel, three card actions and Embed shown to the viewer).
