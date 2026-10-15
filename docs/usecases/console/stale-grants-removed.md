# A grant no longer offered shows as stale and can be removed

Status: current. Id: `uc-056`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Nadia Petrov (Security); password `northfield-demo` |
| agents-service reading tools-service's catalogue | the script passes `OPS_GATEWAY_URL` to the ui harness's agents-service |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James publishes two modules with one read each (Nadia approves their reviews) and grants both reads to a new agent | the agent's `toolIds` are the two reads |
| 2 | He deletes one module | 204; the agent's `staleToolIds` lists that module's read |
| 3 | He opens the agent's Grant tools dialog | the grant is listed under "No longer offered" |
| 4 | Remove, Save grants, then save the agent | 200; `toolIds` is the other read alone and `staleToolIds` is empty |

agents-service reports a grant as stale when its tool directory no longer offers it, and a save drops stale grants
(c-048 T010). A grant of a fixture tool the registry does not list is stale too, so the use case starts from a new agent.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-056-ui.mjs` | passing |

## Non-vacuous check

Step 3 fails on the dialog before c-048 T011, which listed only offered tools, so a stale grant was invisible.
