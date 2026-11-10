# A team turns on the Salesforce plugin, and its agents work cases and cite its articles

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-564`.
Service: `tools-service` with platform-service, kb-service and agents-service. Layers: api, sdk, cli, ui. Guide: `docs/guide/plugins.md`.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Installed, Salesforce is there for every team; a team admin turns it on for the team and signs in once, and Test connection passes | api | 1-7, 51 | 6 |
| S2 | An agent in chat finds a case and, once a person approves a card naming the field it changes, changes it in Salesforce | ui | 13-15 | 15 |
| S3 | A knowledge base syncs the team's Salesforce articles, only changes are fetched again, and chat cites an article | ui | 16-19, 30 | 19 |
| S4 | A team admin turns Salesforce off and its tools disappear; turned on again, everything is still there | api | 8-12 | 10 |
| S5 | A developer validates and tests the plugin, and a broken plugin installed beside it stops nothing else | cli | 20-23 | 22 |
| S6 | A team with no OAuth app of its own signs in with the platform's, a team with its own keeps it, and neither team's account serves the other | api | 24-28 | 26 |
| S7 | On an install with no plugin, none loads and no plugin tool can be granted | cli | 29 | 29 |
| S8 | The app's page lists its tools, and a builder runs one Mock (nothing reaches Salesforce) and Real (the team's account, through the gateway) | api | 40-42, 50 | 42 |
| S9 | An agent granted a new tool offers it in chat right after it is published (task S7) | api | 45 | 45 |
| S10 | A builder lists an app's tools and runs one Mock and Real through the Python SDK | sdk | 43 | 43 |
| S11 | A builder lists an app's tools and runs one Mock and Real with `opsai tools` | cli | 44 | 44 |
| S12 | On an app where each person signs in with their own account, a person's own sign-in runs a tool before any team account exists | api | 47-49 | 49 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | Each layer starts its services with `OPS_PLUGINS=true`; S7 starts tools-service with it off |
| Locked settings | The api layer starts tools-service with `OPS_PLUGIN_LOCKED='{"opsai.salesforce": {"api_version": "61.0"}}'`, the install config that fixes a setting for every team |
| The Salesforce plugin | The `ops-ai-plugins` repository checked out beside ops-ai; each layer names `plugins/salesforce/src/ops_plugin_salesforce` in `OPS_PLUGIN_PATHS` |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`: mock-oauth2-server in Docker behind https, the REST API with cases, Knowledge articles in pages of two (one with an attachment), the limits call, and switches for a token naming a bad host, a 401 and a 429; it records the OAuth app each sign-in used |
| People | Sam Adeyemi (Security admin: the platform admin of this install), Priya Shah (team_ops admin), James Richardson (builder), Maya Okafor (approver), Wanjiru Kamau (team_platform admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya reads the installed plugins, with no admin step before | Salesforce is listed, off for team_ops, with `api_version` locked |
| 2 | Priya turns Salesforce on for team_ops with the team's OAuth app; James tries; Priya tries to set `api_version` | 200 with a new connection; 403 for James; 400 `setting_locked`; the team reads 61.0 |
| 3 | Sam lists Salesforce's hosts and the fake's range | Each 200, 201 or 409 |
| 4 | Priya signs the team in while the token answer names `https://evil.example` | 400 naming the host; no instance kept |
| 5 | Priya signs the team in | 200; the team's `instance_url` is the one the token named |
| 6 | Test connection | Passes, through the limits call |
| 7 | Read the connection and the plugin | The client secret appears in neither |
| 8 | A run calls `salesforce_query` with a SOQL query | 200 at once; the fake received exactly that query |
| 9 | Priya turns Salesforce off for the team | Its tools leave the grantable list; a call answers 403 `APP_OFF_FOR_TEAM` naming the app and team |
| 10 | Priya turns it on again | The same connection and instance; calls run with no new sign-in |
| 11 | Priya turns it off for the team, then on | A call answers 403 `APP_OFF_FOR_TEAM`, then runs again; no restart |
| 12 | Priya edits and deletes the plugin's module | 403 `plugin_module` to both |
| 13 | James asks the case helper in chat about case 00044818 | The agent calls `salesforce_query` and shows the case |
| 14 | James asks it to escalate the case | The approval card names the tool "Update a record", from the plugin's title, and shows the row "Fields · Status: Escalated", never a raw object; `salesforce_update_record` waits in Human Tasks; Salesforce is unchanged |
| 15 | Maya approves it | The fake records the change, made with the team's account |
| 16 | Priya adds a Salesforce articles source to a knowledge base and syncs | Three articles and one attachment indexed, read through the two tools |
| 17 | Sync again | Nothing fetched again |
| 18 | An article changes at the source; sync | Only it is fetched; it becomes version 2 |
| 19 | James asks the agent about resetting a card PIN | The answer cites the Salesforce article |
| 20 | `opsai plugin validate ../ops-ai-plugins/plugins/salesforce` | OK, with its tools, 1 knowledge source and 1 template |
| 21 | `opsai plugin validate` on copies with an unknown sign-in kind, a write used as a knowledge tool, and a template that needs a missing tool | Each refused, naming the problem |
| 22 | `opsai plugin test ../ops-ai-plugins/plugins/salesforce` | Every tool and the knowledge listing pass against the plugin's fake |
| 23 | tools-service starts with a broken plugin beside Salesforce, and a Python tool calls a host the plugin does not list | `/v1/plugins` lists the broken one as failed and Salesforce as loaded; the call fails `EGRESS_DENIED` |
| 24 | The install config holds Ops AI's OAuth app for Salesforce; Sam tries to set its secret through the API | No route sets it (404 or 405); the plugin view shows its client id and that the secret is set, never the secret |
| 25 | Wanjiru turns Salesforce on for team_platform with no app of its own; a team_platform call runs before it signs in | The call is refused; Salesforce receives nothing, though team_ops is signed in |
| 26 | Wanjiru signs the team in | The token exchange carries the platform's client id and secret; team_platform's calls run |
| 27 | Priya signs team_ops in again | The exchange carries team_ops's own app |
| 28 | Read the plugins and team_platform's connection, as Sam and as Wanjiru | The platform's secret appears in none |
| 29 | tools-service starts with an empty plugins folder (`OPS_PLUGINS_DIR`) and no plugin paths | `/v1/plugins` and the team switch answer 404; no `salesforce_` or other plugin tool is grantable |
| 30 | Priya opens the source page while its answer names a source type this console does not know | The page opens with its Sync now button and no page error |
| 40 | Priya reads the app's page (`GET /v1/apps/plugin:opsai.salesforce`) | Its tools list salesforce_query with its title |
| 41 | James runs `POST /v1/tool-modules/{module}/operations/salesforce_query/run` with mode `mock` | 200, `mocked` true; Salesforce received no query |
| 42 | James runs it with mode `real`, naming no environment; the team signed in for production only | 200 with case 00044818 and a call id; Salesforce received the query |
| 43 | Through the SDK on the Apps stack, James lists the header-key desk's tools and runs `header_key_get_record` Mock and Real (`ops.tools.list`, `ops.tools.run`) | The tool listed; Mock reaches nothing; Real reads rec-1042 |
| 44 | James runs `opsai tools list --app plugin:test.header-key`, then `opsai tools run … --mock --input input.json` and `--real` | Each exits 0; Mock reaches nothing; Real reads rec-1042 |
| 45 | With team_ops's publish policy at always, James makes an agent and asks to publish it (the request waits); he grants salesforce_query, saves and asks again; Maya approves; he chats "call salesforce_query …" | The request for the newest draft (201) replaces the one waiting; after Maya approves, the first chat turn calls salesforce_query and reads the case |
| 51 | Priya reads the app's page right after the team's sign-in in step 5 | The team account reads connected at once; its `test` reads ok once the test that follows the sign-in has run |
| 50 | James runs `salesforce_list_view` Real from its page | 200; the records shaped once by the tool's transform, no transform error, and the request sent shown |
| 47 | Sam turns Salesforce on for team_security with `signIn: person` and no team account; a call acting for Sam runs before he signs in | 403 `CONNECTION_NOT_LINKED`, not `APP_OFF_FOR_TEAM` |
| 48 | Sam signs in with his own account | 200; the app's page lists the account as his |
| 49 | The same call acting for Sam | 200 with case 00044818; Salesforce received the query at the address the plugin names, under the instance his sign-in gave |
| 46 | The console steps for group D (the app page's Tools tab, the tool page's Mock or Real, the chat tool row "title · app, as person") | Written by the console builder with tasks U3 and U6 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-564-api.py` | passing, with the Salesforce plugin at ops-ai-plugins main (the instance from UserInfo) |
| ui | `tools-service/scripts/test-uc-564-ui.mjs` | failing at steps 14-15 (2026-11-03), 9 of 11: the escalate write runs before anyone approves (the fake records the edit early). Chat calls carry no run kind, so tools-service treats them as test runs (`gateway_calls.py:256`); a test run's write on the live account should wait (`gateway_calls.py:355`) and did not |
| sdk | `tools-service/scripts/test-uc-564-sdk.py` | target: waits on P1 and K1 |
| cli | `tools-service/scripts/test-uc-564-cli.py` | passing to step 29; 44 target: waits on L2 |

## Non-vacuous check

Each story was seen broken once with its guard removed: step 4 with the token host check skipped, step 9 with the team
switch ignored, steps 14 and 15 with a plugin write let through without approval (Salesforce recorded the edit before
anyone approved), steps 17 and 18 with both the sync's watermark and its marker check removed (every article fetched
again; either one alone keeps the step green), and step 23 with `ctx.http`'s host check removed. Step 18 also failed
before kb-service skipped an unchanged attachment of a changed article, which it fetched again.

On main, step 29 failed before the tool registry hid a plugin's module left from an earlier start with plugins on: all
eight `salesforce_` tools stayed grantable, though every call was refused.

The ui walk sets the plugin up through the API, as steps 1-6 prove it, since there is no Plugins page yet. It
makes the knowledge source through kb-service's API for the same reason, then syncs it from the source's page. The
console masks an eight-digit number in a reply as an account number, so the chat checks match the case's status and
subject rather than its number.
