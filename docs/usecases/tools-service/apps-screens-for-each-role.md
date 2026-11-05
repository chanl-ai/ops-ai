# Apps screens offer only what you may do, in plain words

Status: draft. Id: `uc-626`. Service: `tools-service`. Layers: api, ui.

The Apps screens offered a viewer actions the API then refused (Add custom app, the Auth configs list, Add selected on
Resources), refusals and screens used the service's own words (connections, plugins, gateway, OAuth, team ids), an
app's Settings showed a test result beside the account's state as a second state, and the Connected view said "No
apps match" when nothing was connected. Each answer now says what the caller may do, the console shows only that or
the reason with who to ask, and one state per account reaches every screen.

The ui walk runs on its own stack with two test plugins (`services/tools-service/tests/plugin_kinds/kinds_header_key`,
signed in with a key, and `tests/plugin_templates/templates_desk`, which brings resources); no outside system is
reached. The api layer uses the Apps stack (`docs/usecases/lib/apps_walk.py`).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A refusal on the Apps API is a plain sentence naming the thing and who may act | api | 1 | 1 |
| S2 | A viewer is offered only what they may do, and told who to ask for the rest | ui | 2-4 | 3 |
| S3 | No Apps screen shows an internal word, to an admin or a viewer | ui | 5 | 5 |
| S4 | An app's Settings show the account's one state, as its Auth configs row does | ui | 6 | 6 |
| S5 | With nothing connected, the Connected view says so and how to connect | ui | 7 | 7 |
| S6 | A custom app's Run test that misses a field shows that field, opened, with the reason | ui | 8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Docker, for the api layer's mock OAuth server | Docker running |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | As the viewer, list auth configs, add a custom app, turn an app on, add a secret | Each 403 names the thing and who may act, with no area or action name, team id or internal word |
| 2 | The viewer opens Apps | No Add custom app |
| 3 | The viewer opens Auth configs | "Ask an admin" naming Priya Shah, no error or Try again |
| 4 | The viewer opens a plugin's Resources | No Add selected; who adds them is said |
| 5 | The admin and the viewer read every Apps screen and tab | None of plugin, gateway, module, binding, egress, OAuth, a team id, a cell name |
| 6 | The admin opens the keyed desk's Settings | Its Keys row's state is its Auth configs row's state; no Working, Not tested or Failing beside it |
| 7 | The admin opens the Connected view before anything is connected | "No app is connected yet", not "No apps match" |
| 8 | The admin adds a custom app with an address and key but no test address, and presses Run test | Test address is shown, its section opened, with the reason |
| 9 | Every page | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-626-api.py` | written |
| ui | `tools-service/scripts/test-uc-626-ui.mjs` | written |

## Non-vacuous check

Steps 1, 2, 3, 6 and 7 each failed on the screens and refusals before this change (connections and plugins in the
refusals, Add custom app for a viewer, a 403 with Try again on Auth configs, Working beside the state, No apps match).
