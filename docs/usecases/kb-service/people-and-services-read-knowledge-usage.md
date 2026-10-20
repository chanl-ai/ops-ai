# People and services read knowledge usage, refs, search and workflow refs on one route each

Status: passing. Id: `uc-399`. Service: `kb-service`. Layers: api. Card: c-222.

Knowledge usage, knowledge-base refs, knowledge search and workflow refs were routes only another service could call.
Each now takes a person with the matching cell (agents.view, knowledge.view, workflows.view), who gets their team's
records, and a service holding the matching scope, which keeps the tenant-wide answer it checks against grants itself.
The tool module review import, a copy from a store c-163 retired, is gone.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| kb-service with its files-service, and agents-service with its seeded agents and workflows, in dev | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James (team_ops) and Omar (team_fraud) read `GET /v1/knowledge-usage`; kb-service's token with `agents:view` reads it | James sees his team's agents named for a base they cite; Omar sees the same base with those agents counted, not named; the service reads it |
| 2 | James and Omar each create a base; James lists refs and searches his base and Omar's; agents-service's token with `knowledge:view` lists refs | James lists his base and not Omar's; his search of Omar's base is refused as unknown (404); the service lists both |
| 3 | Each route with a service token holding no scope | 403 `scope_required` |
| 4 | James creates a workflow in team_cards, then reads `GET /v1/workflow-refs` acting in team_ops; tools-service's token with `workflows:view` reads it | James sees only team_ops workflows; tools-service sees every team's, the new one owned by team_cards |
| 5 | `POST /v1/publish-requests/imports` with tools-service's token | Refused as no such route (404 or 405) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-399-api.py` | passing |

## Non-vacuous check

Check 2 fails when kb-service answers a person with the tenant's bases: James's refs then list Omar's base and his
search of it answers 200.
