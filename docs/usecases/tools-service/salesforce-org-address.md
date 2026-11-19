# A team connects Salesforce at its company address and its agents query that org

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-627`.
Service: `tools-service` with platform-service. Layers: api, ui. Guide: `docs/guide/plugins.md`, Sign-in.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin saves the org's My Domain as an auth config's sign-in address, fixed; Connect signs in there, the account keeps the org address Salesforce's token answer names, and salesforce_query returns that org's records with no egress host listed by hand | api | 1-4 | 3 |
| S2 | An auth config holding the address as a default lets a second account sign in at the sandbox's My Domain, and that account's calls reach the sandbox org | api | 5-6 | 6 |
| S3 | In the console, a team admin picks "Your company's address" for a new auth config, connects with it, and runs a SOQL query that returns the org's case | ui | 7-11 | 10 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Docker | The fake Salesforce's sign-in runs mock-oauth2-server in a container |
| Plugins on | Each layer starts its services with `OPS_PLUGINS=true` |
| The Salesforce plugin | The `ops-ai-plugins` repository beside ops-ai at or after chanl-ai/ops-ai-plugins#8, which reads `instance_url` from the token answer; `OPS_SALESFORCE_PLUGIN` names another checkout |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`: a production org on `kestrel.my.salesforce.test` and a sandbox on `kestrel--uat.sandbox.my.salesforce.test`, each signing in at its own My Domain, naming its address as `instance_url` in the token answer, and refusing a token at the other org's host |
| People | Sam Adeyemi (Security admin), Priya Shah (team_ops admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam allows the fake's private range, never its hosts. Priya adds an auth config "Kestrel org" with the sign-in address `https://kestrel.my.salesforce.test/services/oauth2` | The config's field reads that value, fixed, shown as `kestrel.my.salesforce.test` |
| 2 | Priya turns Salesforce on with it and connects | The sign-in opens at `https://kestrel.my.salesforce.test/services/oauth2/authorize` |
| 3 | The fake signs her in | The account's org address is `https://kestrel.my.salesforce.test`, from the token answer; Salesforce's UserInfo is never called |
| 4 | A run calls `salesforce_query` for case 00044818 | Case 00044818; the fake received the query at the org address |
| 5 | Priya adds "Kestrel default" holding the same address as a default, and an account on it at `https://kestrel--uat.sandbox.my.salesforce.test/services/oauth2` | It signs in at the sandbox's My Domain and keeps `https://kestrel--uat.sandbox.my.salesforce.test` |
| 6 | A run calls `salesforce_query` on that account | Case 00044818 from the sandbox org |
| 7 | In the console, Priya opens Salesforce, Auth configs, New auth config, and picks "Your company's address" with `kestrel.my.salesforce.test` | The config's row reads that sign-in place |
| 8 | She connects Salesforce with the new config | The Connect window shows the config's address and asks nothing; the sign-in window opens on the My Domain |
| 9 | The fake signs her in | The app's page reads Connected, and the account's row shows its org address |
| 10 | She runs Run a SOQL query from the tool's Test with the case query | The answer holds case 00044818 |
| 11 | Every page | No page errors |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 3 | The UserInfo call count is read before and after the sign-in; a plugin still reading the lookup fails the step (red on the manifest before #8) |
| 4, 6 | The fake answers a token only at its own org's host, so a call sent anywhere else is refused 401 |
| 4 | No egress host is listed, so a call allowed only by a manual entry is refused |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-627-api.py` |
| ui | `docs/usecases/tools-service/scripts/test-uc-627-ui.mjs` |
