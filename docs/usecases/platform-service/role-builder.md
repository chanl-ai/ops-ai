# A person invited as a builder builds the team's agents and decides nothing

Status: current. Id: `uc-217`. Service: `platform-service`, agents-service, console. Layers: api, ui.

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
| 1 | Priya invites a new address as builder | They join team_ops as builder |
| 2 | They create and edit an agent and ask to publish it | Created, saved, and the request waits for review |
| 3 | They decide their own request | 403 |
| 4 | They invite someone, change a policy | 403 each |
| 5 | ui: they open their agent, the pending review and Access | Editable with no View only; who decides and no Approve; no Invite |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-217-api.py` | passing |
| ui | `platform-service/scripts/test-uc-217-ui.mjs` | passing |

## Non-vacuous check

Inviting uc-216's person as admin instead of viewer fails six of its checks.
