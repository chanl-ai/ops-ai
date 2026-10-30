# A builder picks a knowledge base past the first hundred and a tool, searched on the server

Status: current. Id: `uc-113`. Service: `console`. Layers: ui.

Card an earlier change: the agent page's knowledge and tools pickers are `EntityPicker` over `/options` routes, so the search runs
on the service and nothing is capped by what the browser loaded. Knowledge is stored by knowledge base id.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder of team_ops); password `northfield-demo` |
| 120 knowledge bases in team_ops | created through kb-service's API by the script |
| A grantable tool | the scripted stack's fixture catalogue (lookup_account) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens a new agent's page and searches the knowledge picker for the 118th base | the search goes to kb-service's options route and the base is offered |
| 2 | He picks it | a chip shows its name |
| 3 | He searches the tools picker and grants lookup_account | the search goes to agents-service's options route; a chip shows the tool |
| 4 | He saves the version | the version stores the base's id and the tool's id |
| 5 | He reloads | both chips show names, resolved by id |

## Acceptance layers

| Layer | Script |
|---|---|
| ui | `docs/usecases/console/scripts/test-uc-113-ui.mjs` |
