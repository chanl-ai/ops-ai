# An agent queries Salesforce seven ways, a page at a time, and nothing it types changes a query

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-581`.
Service: `tools-service` with platform-service, kb-service and agents-service. Layers: api, ui, cli. Card: an earlier change.
Design: `docs/guide/plugins.md`, Paging and queries.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent reads a listing a page at a time with a sealed cursor, and a value or cursor that would change the query never reaches Salesforce | api | 1-4 | 3 |
| S2 | An agent runs seven kinds of query on one account's data and each answers the records the data holds for it | api | 5-11 | 5 |
| S3 | A knowledge base syncs Salesforce's articles through a listing that is plain plugin data, and a page Salesforce has forgotten restarts the listing instead of failing every run | ui | 12-15 | 14 |
| S4 | A builder finds a plugin's tools by their titles in the tools picker, and the agent lists them by title | ui | 16-17 | 16 |
| S5 | A developer is told, by field, when a plugin's paging rule or query input could not run safely | cli | 18-21 | 19 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | Each layer starts its services with `OPS_PLUGINS=true` |
| The Salesforce plugin | The `ops-ai-plugins` repository checked out beside ops-ai, with the seven query tools (chanl-ai/ops-ai-plugins#1); each layer names `plugins/salesforce/src/ops_plugin_salesforce` in `OPS_PLUGIN_PATHS` |
| A fake Salesforce | `docs/usecases/lib/fake_salesforce.py`: one account (Acme Card Services) with three open escalated cases and one in the recycle bin, a contact, a list view of escalated cases, Knowledge articles in pages of two, and switches for a 429 on the listing's second page and for forgetting saved query locators; it records every query it answers |
| People | Sam Adeyemi (Security admin, the platform admin of this install), Priya Shah (team_ops admin), James Richardson (builder); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | An agent's run calls `salesforce_find_cases` for escalated cases changed since 2026-10-01T11:00:00+02:00 | The first two cases and a sealed `next_cursor`; Salesforce received `Status = 'Escalated'` and `LastModifiedDate > 2026-10-01T09:00:00Z` in the SOQL; Salesforce's own next address is not in the answer |
| 2 | It calls again with only the cursor | The third case, and no further cursor |
| 3 | It asks with the status `Escalated' OR Status != '`, the date `2026' OR Name != '`, and the account id `001' OR Id != '` | Each refused; Salesforce receives no query |
| 4 | It sends the cursor with its end changed, and a cursor that `salesforce_account_cases` gave | Both refused `INVALID_INPUT`; Salesforce receives nothing |
| 5 | `salesforce_find_cases_with_deleted` for escalated cases | The deleted case appears, marked `IsDeleted`; steps 1-2 never showed it |
| 6 | `salesforce_search` for "Acme", then for `card} RETURNING User(Email` | The account, its contact and its cases; the second term reaches Salesforce escaped, inside `FIND {...}` |
| 7 | `salesforce_search_by_fields` for "card", Escalated, fields Id and Subject | The three open cases, each with only Id and Subject |
| 8 | `salesforce_account_cases` for Acme, then its cursor | The three open cases over two pages |
| 9 | `salesforce_cases_changed` between 2026-10-04 and 2026-10-07 12:00 | The two open cases changed in that window, by id |
| 10 | `salesforce_list_view` for the escalated view, page after page | The three open cases, one page each by token, each with flat fields |
| 11 | The gateway's list of tools agents may be granted | All seven query tools, each with its title |
| 12 | Priya adds a Salesforce articles source to a knowledge base and syncs | Three articles and one attachment indexed, listed by the plugin's data listing tool |
| 13 | Salesforce answers the listing's second page with 429; Priya syncs a full listing | The run stops partial, its place saved |
| 14 | Salesforce forgets every saved query locator; Priya syncs again | The run starts the listing again from its watermark and succeeds, instead of failing on the forgotten page |
| 15 | Priya syncs once more | Nothing is fetched again |
| 16 | James opens the case helper's tools picker and searches "find cases" | The option reads "Find cases", from Salesforce |
| 17 | James grants it and reloads the agent | The granted tool reads "Find cases" on the agent page |
| 18 | `ops plugin validate` on a copy whose `find_cases` link paging names no field | Refused: "a link rule names the answer field" |
| 19 | On a copy whose `find_cases` status input has no list or format | Refused: "status is used in a query and needs an enum or a format" |
| 20 | On a copy whose `search` term input has only a pattern | Refused: "term has only a pattern, which is for path segments" |
| 21 | On a copy with an input nested four levels deep | Refused: "nests past three levels" |

The approval card's title for a plugin tool ("Update a record") is checked in uc-564 step 14, whose walk already
raises that card.

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 3 | The fake's query count is read before and after: a refusal that still sent a query fails the step |
| 4 | The cursor from another tool is a real one, so only the seal's tool check can refuse it |
| 5 | Step 5 needs the deleted case present and steps 1-2 to have left it out; either path broken fails it |
| 14 | Step 13 must first leave a saved place; step 14 passes only if a forgotten locator ended in success |

## Results

| Layer | Script | Result |
|---|---|---|
| api | `tools-service/scripts/test-uc-581-api.py` | passing (2026-10-30), 14 checks |
| ui | `tools-service/scripts/test-uc-581-ui.mjs` | passing (2026-10-30), 9 checks |
| cli | `tools-service/scripts/test-uc-581-cli.py` | passing (2026-10-30), 5 checks |
