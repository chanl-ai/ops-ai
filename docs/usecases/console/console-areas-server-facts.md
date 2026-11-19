# The facts the console's areas depend on come from the services

Status: draft. Id: `uc-722`. Service: `console` with `tools-service` and `platform-service`. Layers: api.

The areas are drawn from `GET /v1/me/permissions`, and the chat's "Open call" link opens the tool-call page on one call
by its id. Design: the console areas design page, acceptance criteria section.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The people used to prove the areas hold the cells they are meant to | api | 1, 2, 3 | 3 |
| S2 | The tool-call list can show one call by its id | api | 4, 5, 6 | 5 |

## Preconditions

| Needs | How |
|---|---|
| platform-service and tools-service on the run's database | `platform()` and `tools()` from the harness |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Lena (chat user) reads her permissions | Chat, and no page's view cell |
| 2 | Tomas reads them in Operations and in Platform | Builder cells in Operations; chat alone in Platform |
| 3 | Ravi and Maya read theirs | Maya holds `activity.view`; Ravi does not |
| 4 | Two tool calls are made in one thread | Both are logged |
| 5 | `GET /v1/executions?call=<id>` | Exactly that call |
| 6 | The same with an id that does not exist | No rows |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-722-api.py` | failing |

## Non-vacuous check

Step 5 expects one row where the thread holds two: a list that ignores the `call` filter returns both.
