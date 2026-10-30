# A builder pages and searches a growing list on the server

Status: current. Id: `uc-098`. Service: `console`. Layers: ui.

Card an earlier change: Guardrails, Widgets, Egress hosts, Secrets, Wiki collections and a connection's sources ask the API for one
page and its total (`?page=&pageSize=&search=`) instead of loading every row and paging in the browser. This use case
drives Guardrails, on agents-service, end to end.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder of team_ops); password `northfield-demo` |
| Twelve guardrails | created through `POST /v1/guardrails` by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Guardrails | ten rows, "Page 1 of 2", the total from the API; the request carries `page=1` |
| 2 | He goes to the next page | the remaining rows; the request carries `page=2` |
| 3 | He searches one guardrail's name | one row, page 1, the total shrinks to 1 |

## Acceptance layers

| Layer | Script |
|---|---|
| ui | `docs/usecases/console/scripts/test-uc-098-ui.mjs` |
