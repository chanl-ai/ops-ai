# A plugin sends the headers, forms, sign-in steps and limits a system needs

Status: current on main behind the `OPS_PLUGINS` switch, which each layer turns on for its own services. Id: `uc-584`.
Service: `tools-service` with platform-service. Layers: api, cli. Guide: `docs/guide/plugins.md`, Headers,
forms and sign-in steps.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A plugin's headers, its own and a tool's, reach the system beside the team's sign-in, on a data tool and a Python tool; a team setting that would carry a secret reference turns the plugin's calls off | api | 1-4 | 4 |
| S2 | A tool posts form fields as Slack's methods take them, and a transfer over its amount limit, or with no amount, never leaves | api | 5-6 | 6 |
| S3 | A Zoom-style app sends its client as basic auth on every token call, and a sign-in address carries the plugin's parameters without replacing the platform's | api | 7-8 | 8 |
| S4 | The lookup after sign-in finds the team's site; a person's own sign-in on another site is refused and holds no token; a lookup naming an unusable value fails the sign-in; the team admin's sign-in moves the site; Salesforce reads its instance from UserInfo and sends its query options | api | 8-12 | 9 |
| S5 | A developer is told, by field, when a plugin's header, sign-in parameter, lookup, limit or request could carry a secret, replace the sign-in or reach a host it does not list | cli | 13-18 | 13 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | The api layer starts tools-service with `OPS_PLUGINS=true` and `OPS_PLUGIN_PATHS` naming `services/tools-service/tests/plugin_fields`'s three plugins, then again naming the Salesforce plugin |
| A fake system | `docs/usecases/lib/fake_multi_auth.py`: shows the non-credential headers it was sent, takes chat messages only as a form, counts transfers, refuses the Zoom-style client unless it comes as basic auth, records each sign-in address, and answers the sites lookup with a site a control switches |
| The Salesforce plugin | `OPS_SALESFORCE_PLUGIN` naming its folder, else the `ops-ai-plugins` repository beside ops-ai, at the version that reads its instance from UserInfo (chanl-ai/ops-ai-plugins, draft pull request) |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`: answers UserInfo on its sign-in host in Salesforce's format and records the `Sforce-Query-Options` each query-all carried |
| People | Sam Adeyemi (Security admin), Priya Shah (team_ops admin), James Richardson (builder); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The platform admin turns the three test plugins on; Security lists the fake's hosts | All three load and read as on |
| 2 | Priya turns on the fields desk with its token; a run calls `fields_search` | The fake saw `X-Api-Version: 2026-10`, `ConsistencyLevel: eventual` and the team's token |
| 3 | A run calls `fields_echo`, a Python tool | Its request carried `X-Api-Version`; the answer holds no token |
| 4 | Priya sets `api_version` to `{{OPS_SECRETS_KEY}}`; a run calls `fields_search` | `PLUGIN_DISABLED` naming `api_version`; the fake received nothing |
| 5 | A run calls `fields_post_message` for C024BE91L, "Card 1042 & more" | The fake took a form with both fields and answered `ok` |
| 6 | A run transfers 4999.50, then 5000.01, then no amount | The first is sent; `amount_over_limit`; 422; the fake counted one transfer |
| 7 | Priya turns on the meetings desk with the Zoom-style app; a run calls `fields_zoom_get_record` | Every token request sent the client as basic auth and was accepted; the call answered as the client |
| 8 | Priya turns on the sites desk for people or the team, and signs in the team's account; a run calls `fields_sites_get_record` | The sign-in address carried `audience=api.multi.test`, `prompt=consent` and the platform's own `state` and `client_id`; the lookup found `site-7f3a`; the call reached it |
| 9 | The fake now names `site-other`; James signs in with his own account | Refused, "signed in to another site"; Your connections shows him not connected; the team still points at `site-7f3a` |
| 10 | The fake names `../admin?x=1`, Priya signs in the team's account; then it names `site-other` and she signs in again | The first fails; the second moves the team's calls to `site-other` |
| 11 | Every answer in the run is searched for the token and the client secrets | None found |
| 12 | Priya turns Salesforce on and signs in; a run calls `salesforce_find_cases_with_deleted` | The fake saw a UserInfo call; the cases come back from the instance it named; query-all carried `batchSize=2000` |
| 13 | `ops plugin validate` on the fields desk as it is | OK |
| 14 | On a copy whose plugin header is named `Authorization` | Refused at `headers.Authorization`: "carries the sign-in" |
| 15 | On a copy whose header reads `{{API_KEY}}` | Refused: "holds {{" |
| 16 | On a copy of the sites desk with a `state` sign-in parameter, and one whose lookup reaches `evil.test` | Refused: "set by the platform"; "not one of the plugin's egress hosts" |
| 17 | On a copy whose transfer limit reads an input that is not `amount` | Refused: "a number input named amount" |
| 18 | On a copy whose form tool also has a JSON body | Refused: "a JSON body or a form, not both" |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | The fake records the credential's digest as well as the headers: a header that replaced the sign-in fails it |
| 4 | The fake's call count is read before and after: a call refused after sending fails the step |
| 6 | The transfer count is read after the refused calls, so a refusal that still sent fails it |
| 9 | Your connections is read after the refusal: a token stored for James fails it |
| 12 | The fake records UserInfo calls; a plugin still reading the token's instance makes none |

## Results

| Layer | Script | Result |
|---|---|---|
| api | `tools-service/scripts/test-uc-584-api.py` | passing (2026-10-31), 12 checks; step 12 against the Salesforce plugin's draft pull request branch |
| cli | `tools-service/scripts/test-uc-584-cli.py` | passing (2026-10-31), 7 checks |

Evidence only, not in the nightly run: `tools-service/scripts/evidence-uc-584-stripe.py` sends a `Stripe-Version` header,
a form-encoded customer create and a payment intent under an amount limit to Stripe in test mode; passing (2026-10-31),
4 checks.
