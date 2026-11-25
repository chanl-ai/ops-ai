# An agent's tools are chosen by app

Status: draft. Id: `uc-agents-1`. Service: `agents-service`. Layers: api, ui.

Short title: Choose an agent's tools by app

A builder gives an agent its tools one app at a time. They search for a tool or an app, open the app, select all of
its tools or some of them, and add them in one save. The agent's page then lists its tools grouped by app, with how
many of the app's tools the agent holds. The search, the grouping and the counts come from the server.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder finds an app by the name of one of its tools and reads that app's tools | api | 1-2 | 1 |
| S2 | Granting all of an app's tools in one save shows the app with every tool counted and marked | api | 3-4 | 4 |
| S3 | An app nobody has answers not found | api | 5 | 5 |
| S4 | A builder opens Add tools, searches for a tool and opens its app | ui | 6-8 | 7 |
| S5 | Select all, then Add, grants the tools in one save; the Tools section shows the app's row and Publish stays usable | ui | 9-10 | 10 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-agents-1 LAYER=api` (or `ui`) |

Both layers run agents-service on the scripted model, on a database the run owns, removed when the run ends. Its
fixture tools belong to several systems, and each system is one app here. tools-service is not started, so no app is
connected or waiting for a sign-in; the service tests in `services/agents-service/tests/api/test_tool_apps.py` cover
connected apps, an app's tools the team has not added, another team's agent, paging and tools-service being down. Each
run makes one agent and calls no model.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/agents/{id}/tool-apps?search=<a tool's name>` | 200; the tool's app, the tool under `matches`, `toolsGranted` 0 |
| 2 | `GET /v1/agents/{id}/tool-apps/{appId}/tools` | 200; that app's tools and no other system's, none granted |
| 3 | Save the agent with every tool of the app | 200; the stored tools are those |
| 4 | Read the apps with `granted=true`, then the app's tools | One app, `toolsGranted` equal to `toolsOffered`; every tool marked granted |
| 5 | `GET /v1/agents/{id}/tool-apps/app_nobody_has/tools` | 404 `not_found` |
| 6 | On the agent's page, press Add tools | A dialog with a search field and a card for each app the server lists |
| 7 | Type a tool's name in the search | Its app's card stays, the tool is listed under it, the other apps' cards go |
| 8 | Open the app and press Select all | The app's tools are listed; the button reads "Add N tools" |
| 9 | Press Add N tools | One save of the agent's tools, holding all N |
| 10 | Read the Tools section and the header | One row for the app, reading "N of M tools"; Publish is not disabled |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-agents-1-api.py` | failing until the two routes exist |
| ui | `agents-service/scripts/test-uc-agents-1-ui.mjs` | written, not yet run |
| sdk | none | `agents.toolApps` and `agents.toolAppTools` are checked by `make sdk-verify`; no sdk script yet |

## Non-vacuous check

`4 the agent's apps are that one app, with every tool counted and marked as granted` fails when the counts are not
read from the agent's own grants. `5` fails when an unknown app answers an empty list, and is paired with step 2,
which answers. `7` fails when the search filters the cards in the browser, since the cards must match the server's
answer for the typed words. `9` fails when Select all sends one save per tool. `10` fails when a grant leaves the
page marked as unsaved, which disables Publish.
