# An agent's tools are chosen by app

Status: draft. Id: `uc-agents-1`. Service: `agents-service`. Layers: api, ui.

Short title: Choose an agent's tools by app

A builder gives an agent its tools one app at a time. They search for a tool or an app, open the app, tick the tools they
want, and add them in one save. The agent's page then lists its tools grouped by app, with how
many of the app's tools the agent holds. The search, the grouping and the counts come from the server.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder finds an app by the name of one of its tools and reads that app's tools | api | 1-2 | 1 |
| S2 | Granting all of an app's tools in one save shows the app with every tool counted and marked | api | 3-4 | 4 |
| S3 | An app nobody has answers not found | api | 5 | 5 |
| S4 | A tool the agent holds stays listed when nothing offers it any more, or tools-service is out of reach | api | 6-7 | 7 |
| S5 | A builder opens Add tools, searches for a tool and opens its app | ui | 8-10 | 9 |
| S6 | Ticking tools, then Add, grants the tools in one save; the Tools section shows the app's row and Publish stays usable | ui | 11-12 | 12 |
| S7 | A granted agent that was paused stays on the page with Remove, and the header counts the tools drawn | ui | 13 | 13 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-agents-1 LAYER=api` (or `ui`) |

Both layers run agents-service on the scripted model, on a database the run owns, removed when the run ends. Its
fixture tools belong to several systems, and each system is one app here. tools-service is not started, so no app is
connected or waiting for a sign-in. Each run makes two agents and calls no model. For step 7 the api script starts
agents-service a second time on the same database, pointed at a tools-service address nothing answers.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/agents/{id}/tool-apps?search=<a tool's name>` | 200; the tool's app, the tool under `matches`, `toolsGranted` 0 |
| 2 | `GET /v1/agents/{id}/tool-apps/{appId}/tools` | 200; that app's tools and no other system's, none granted |
| 3 | Save the agent with every tool of the app | 200; the stored tools are those |
| 4 | Read the apps with `granted=true`, then the app's tools | One app, `toolsGranted` equal to `toolsOffered`; every tool marked granted |
| 5 | `GET /v1/agents/{id}/tool-apps/app_nobody_has/tools` | 404 `not_found` |
| 6 | Publish a second agent, grant it to the first as a tool, then pause it | It is no longer offered; every tool the agent holds is still named, by an app's granted tools or by `staleToolIds` |
| 7 | Start agents-service with tools-service out of reach and read the same lists | 200; every tool the agent holds is still named |
| 8 | On the agent's page, press Add tools | A dialog with a search field and a card for each app the server lists |
| 9 | Type a tool's name in the search | Its app's card stays, the tool is listed under it, the other apps' cards go |
| 10 | Open the app and tick each of its tools | The app's tools are listed; the button reads "Add N tools" |
| 11 | Press Add N tools | One save of the agent's tools, holding all N |
| 12 | Read the Tools section and the header | One row for the app, reading "N of N tools"; Publish is not disabled |
| 13 | Grant a second, published agent as a tool, pause it and reload the page | Each tool the agent holds has a Remove button, and the header's count equals them |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-agents-1-api.py` | Steps 1 to 5 pass; 6 and 7 fail: a paused agent's grant, and every operation grant while tools-service is out of reach, is named by neither list |
| ui | `agents-service/scripts/test-uc-agents-1-ui.mjs` | Steps 8 to 13, with pictures at 1440 and 390 wide under `.logs/usecases/uc-agents-1/ui/`; 13 fails for the reason step 6 does |
| sdk | none | `agents.toolApps` and `agents.toolAppTools` are checked by `make sdk-verify`; no sdk script yet |

What each layer proves, and what neither does:

| Behaviour | api | ui | Elsewhere |
|---|---|---|---|
| Search by a tool's words, an app's tools, counts and granted marks | 1-4 | 9, 10, 12 | |
| Unknown app answers 404 | 5 | | |
| All of an app's tools added in one save | 3 | 11 (one request from the page) | |
| Publish stays usable after a grant of a fixture tool | | 12 | |
| A grant nothing offers any more stays listed | 6 | 13 | |
| Grants stay listed while tools-service is out of reach | 7 | not checked: a ui stack cannot point agents-service at an address nothing answers | |
| Publish stays usable after a grant of an imported tool | | not here: this stack starts no tools-service | uc-055 ui grants two imported bank tools through the picker and then presses Publish |
| Connected, sign-in and not-added states, the Connect panel, another team's agent, paging, view rights | | | `services/agents-service/tests/api/test_tool_apps.py` for the API; the console's states have no script |

## Non-vacuous check

`4 the agent's apps are that one app, with every tool counted and marked as granted` fails when the counts are not
read from the agent's own grants. `5` fails when an unknown app answers an empty list, and is paired with step 2,
which answers. `6` and `7` fail when a tool the agent holds is named by no list, so the page cannot draw it. `9` fails
when the search filters the cards in the browser, since the cards must match the server's answer for the typed words.
`11` fails when adding the ticked tools sends one save per tool. `12` fails when a grant leaves the page marked as unsaved, which
disables Publish. `13` fails when the header counts a tool the page gives no way to remove.
