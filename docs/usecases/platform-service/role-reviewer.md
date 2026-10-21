# A person invited as a reviewer decides a builder's publish request and edits no agent

Status: current. Id: `uc-218`. Service: `platform-service`, agents-service, console. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; run the ui layer with `ISOLATED=1` |

platform-service runs with the dev seed's own roles (`OPS_SEED_EVERYONE_ADMIN` off) and agents-service verifies its
tokens. The person checked is never a seeded one: an admin invites them through the product and they accept with a
password (c-218). No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites a builder and a reviewer (stored `approver`) | Both join team_ops |
| 2 | The builder asks to publish an agent | The request waits |
| 3 | The reviewer approves it (ui: from Reviews) | Approved |
| 4 | The reviewer creates or edits an agent (ui: opens it) | 403 each; the page says View only |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-218-api.py` | passing |
| ui | `platform-service/scripts/test-uc-218-ui.mjs` | passing |

## Non-vacuous check

Inviting uc-216's person as admin instead of viewer fails six of its checks.
