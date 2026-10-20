# A person invited as a Security team admin sets sign-in and policies, and the right moves with the security team

Status: current. Id: `uc-220`. Service: `platform-service`, agents-service, console. Layers: api, ui.

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
| 1 | Sam, admin of team_security, invites a new address as admin there | They join team_security as admin |
| 2 | They set a sign-in provider and a policy | 200 each |
| 3 | Priya, admin of team_ops, does the same | 403 each |
| 4 | Wanjiru makes team_ops the security team | The invited admin is refused (403); Priya now succeeds |
| 5 | ui: both open Settings > Sign-in | The Security team admin sees the providers and Add provider; Priya's team's admin is told the Security team sets sign-in |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-220-api.py` | passing |
| ui | `platform-service/scripts/test-uc-220-ui.mjs` | passing |

## Non-vacuous check

Inviting uc-216's person as admin instead of viewer fails six of its checks (`.codeloop/evidence/218/red-viewer-invited-as-admin.txt`).
