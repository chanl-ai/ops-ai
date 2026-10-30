# A team turns on the Salesforce plugin, and its agents work cases and cite its articles

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-564`.
Service: `tools-service` with platform-service, kb-service and agents-service. Layers: api, ui, cli. Cards: an earlier change (the
prototype), an earlier change (on main). Design: the planning repo `docs/plans/ops-ai/plugin-architecture.html` and
`plugin-contents-and-knowledge.html`.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The platform admin turns Salesforce on, a team admin turns it on for the team and signs in once, and Test connection passes | api | 1-7 | 6 |
| S2 | An agent in chat finds a case and, once a person approves a card naming the field it changes, changes it in Salesforce | ui | 13-15 | 15 |
| S3 | A knowledge base syncs the team's Salesforce articles, only changes are fetched again, and chat cites an article | ui | 16-19, 30 | 19 |
| S4 | A team admin turns Salesforce off and its tools disappear; turned on again, everything is still there | api | 8-12 | 10 |
| S5 | A developer validates and tests the plugin, and a broken plugin installed beside it stops nothing else | cli | 20-23 | 22 |
| S6 | A team with no OAuth app of its own signs in with the platform's, a team with its own keeps it, and neither team's account serves the other | api | 24-28 | 26 |
| S7 | With plugins switched off, no plugin loads and none of its tools can be granted | cli | 29 | 29 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | Each layer starts its services with `OPS_PLUGINS=true`; S7 starts tools-service with it off |
| The Salesforce plugin | The `ops-ai-plugins` repository checked out beside ops-ai; each layer names `plugins/salesforce/src/ops_plugin_salesforce` in `OPS_PLUGIN_PATHS` |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`: mock-oauth2-server in Docker behind https, the REST API with cases, Knowledge articles in pages of two (one with an attachment), the limits call, and switches for a token naming a bad host, a 401 and a 429; it records the OAuth app each sign-in used |
| People | Sam Adeyemi (Security admin: the platform admin of this install), Priya Shah (team_ops admin), James Richardson (builder), Maya Okafor (approver), Wanjiru Kamau (team_platform admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam sets the `plugins` policy: Salesforce on, `api_version` locked at 61.0; James tries the same | 200 for Sam; 403 for James |
| 2 | Priya turns Salesforce on for team_ops with the team's OAuth app; James tries; Priya tries to set `api_version` | 200 with a new connection; 403 for James; 400 `setting_locked`; the team reads 61.0 |
| 3 | Sam lists Salesforce's hosts and the fake's range | Each 200, 201 or 409 |
| 4 | Priya signs the team in while the token answer names `https://evil.example` | 400 naming the host; no instance kept |
| 5 | Priya signs the team in | 200; the team's `instance_url` is the one the token named |
| 6 | Test connection | Passes, through the limits call |
| 7 | Read the connection and the plugin | The client secret appears in neither |
| 8 | A run calls `salesforce_query` with a SOQL query | 200 at once; the fake received exactly that query |
| 9 | Priya turns Salesforce off for the team | Its tools leave the grantable list; a call answers 403 `PLUGIN_DISABLED` |
| 10 | Priya turns it on again | The same connection and instance; calls run with no new sign-in |
| 11 | Sam turns it off for the install, then on | Within six seconds calls are refused, then run again; no restart |
| 12 | Priya edits and deletes the plugin's module | 403 `plugin_module` to both |
| 13 | James asks the case helper in chat about case 00044818 | The agent calls `salesforce_query` and shows the case |
| 14 | James asks it to escalate the case | The approval card names the tool "Update a record", from the plugin's title, and shows the row "Fields · Status: Escalated", never a raw object; `salesforce_update_record` waits in Human Tasks; Salesforce is unchanged |
| 15 | Maya approves it | The fake records the change, made with the team's account |
| 16 | Priya adds a Salesforce articles source to a knowledge base and syncs | Three articles and one attachment indexed, read through the two tools |
| 17 | Sync again | Nothing fetched again |
| 18 | An article changes at the source; sync | Only it is fetched; it becomes version 2 |
| 19 | James asks the agent about resetting a card PIN | The answer cites the Salesforce article |
| 20 | `ops plugin validate ../ops-ai-plugins/plugins/salesforce` | OK, with its tools, 1 knowledge source and 1 template |
| 21 | `ops plugin validate` on copies with an unknown sign-in kind, a write used as a knowledge tool, and a template that needs a missing tool | Each refused, naming the problem |
| 22 | `ops plugin test ../ops-ai-plugins/plugins/salesforce` | Every tool and the knowledge listing pass against the plugin's fake |
| 23 | tools-service starts with a broken plugin beside Salesforce, and a Python tool calls a host the plugin does not list | `/v1/plugins` lists the broken one as failed and Salesforce as loaded; the call fails `EGRESS_DENIED` |
| 24 | Sam sets up the platform's OAuth app: its client id in the `plugins` policy, its secret with `PUT /v1/plugins/opsai.salesforce/app-secret`; Priya tries the secret | 200 for Sam; 403 for Priya |
| 25 | Wanjiru turns Salesforce on for team_platform with no app of its own; a team_platform call runs before it signs in | The call is refused; Salesforce receives nothing, though team_ops is signed in |
| 26 | Wanjiru signs the team in | The token exchange carries the platform's client id and secret; team_platform's calls run |
| 27 | Priya signs team_ops in again | The exchange carries team_ops's own app |
| 28 | Read the plugins and team_platform's connection, as Sam and as Wanjiru | The platform's secret appears in none |
| 29 | tools-service starts with `OPS_PLUGINS=false`, the same plugin folders and the install switch on | `/v1/plugins` and the team switch answer 404; no `salesforce_` or other plugin tool is grantable |
| 30 | Priya opens the source page while its answer names a source type this console does not know | The page opens with its Sync now button and no page error |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-564-api.py` | passing |
| ui | `tools-service/scripts/test-uc-564-ui.mjs` | passing |
| cli | `tools-service/scripts/test-uc-564-cli.py` | passing |

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
