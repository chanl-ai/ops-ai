# Guardrail names are unique per team

Status: draft. Id: `uc-731`. Service: `agents-service`. Layers: api.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder who makes a second guardrail with a name their own team already uses is told the name is taken, and the first keeps its plain name | api | 1, 2 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | In Operations, create the guardrail "No investment advice" | 201, slug `no-investment-advice` |
| 2 | In Operations, create it a second time | 409 `name_taken` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-731-api.py` | written |

## Non-vacuous check

Step 2 fails while a repeated name is renamed to `no-investment-advice-2` and saved. Another team keeping the same
slug needs a stack with signed-in people in two teams; the dev header stack acts in one team, so that half is covered
by the agents-service route test and the migration test.
