# A team takes in SharePoint libraries and Confluence spaces

Status: current. Id: `uc-678`. Service: `kb-service` with tools-service. Layers: api, sdk, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team signs SharePoint in through Microsoft with its own app and Confluence with an API token, and Add source picks sites, then their libraries, and spaces by searching for them | api | 0-2, 5 | 2 |
| S2 | The first sync takes in the picked libraries' files, Markdown, text, PDF and Word, each kept as a snapshot file with who may read it | api | 3 | 3 |
| S3 | A file changed and one deleted in SharePoint are found by the delta query; only the changed file is fetched again, and the deleted one leaves search | api | 4 | 4 |
| S4 | An edited Confluence page is the only page fetched again, and an agent given the base cites a SharePoint file and a Confluence page | api | 5-7 | 6 |
| S5 | In the console, Add source's pickers search sites, select all, list the picked site's libraries, and show an empty and an error state; Create and sync indexes the files | ui | 10-14 | 12 |
| S6 | A developer asks the pickers through the Python and TypeScript SDKs | sdk | 8-9 | 9 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and Docker (OPA) | `make db-up`; the scripts start tools-service, kb-service, files-service, documents-service (and agents-service for step 7) on the run's own ports and database |
| The plugins | The plugins checkout holding `plugins/sharepoint` and `plugins/confluence` (`OPS_PLUGINS_REPO`, else `ops-ai-plugins` beside this checkout), loaded into tools-service and kb-service through `OPS_PLUGIN_PATHS` |
| A SharePoint tenant and a Confluence site | `docs/usecases/lib/fake_sharepoint_confluence.py`: the plugins' own fakes (`FakeGraph`, `FakeConfluence`) served on https on this machine's private address as `graph.microsoft.com`, `contoso.sharepoint.com`, `acme.atlassian.test` and `api.media.atlassian.com`, with one certificate tools-service trusts (`OPS_EGRESS_CA_FILE`) and a name map (`OPS_EGRESS_RESOLVE`, dev only) |
| The team's sign-ins | `login.microsoftonline.com` is `fake_token_endpoint.py`'s code sign-in (PKCE S256, the client's secret, a refresh token) for an Entra app with a client secret made per run; Confluence takes a basic credential (an email and an API token) made per run. Graph answers only a token the sign-in issued and Confluence only that credential. Neither secret is printed |
| Egress | Security allows the five hosts and the fakes' private range, as for any outside system |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | A team admin adds the team's Entra app (client id, secret), turns SharePoint on with it and signs in through Microsoft; turns Confluence on with an email and API token and tests it | The sign-in opens `login.microsoftonline.com/organizations/oauth2/v2.0/authorize`, finishes, and reads the tenant's SharePoint address from `/sites/root`; Add source lists both as connected, with pickers |
| 1 | `POST /v1/sources/scopes` for SharePoint with the query "human" | Human Resources, as a site |
| 2 | The same with the site as parent; with a library as parent; a query nothing matches; a query Graph answers 503 for | The site's two libraries under it; nothing (a library holds nothing to pick, and Add source asks every picked value); no sites; 503 `scopes_failed` naming Graph's 503 |
| 3 | Create the source on the site and both libraries, sync | All four files indexed with a file id, the PDF and Word file read by documents-service; each version's `allowed` (`GET /v1/items/{id}`) is the user and group ids Graph lists on the file, stored and not yet enforced in search; search cites `leave.md` by its library address and finds the PDF's text |
| 4 | Edit `expenses.txt` and delete `leave.md` at Graph, sync | Only `expenses.txt` is downloaded again (one upsert); `leave.md` leaves the source and search; search quotes the new text |
| 5 | Search spaces for "eng", create a source on ENG, sync | Engineering alone offered; its three pages indexed; search cites Deploys |
| 6 | Edit page 101, sync | Only page 101's body is fetched again (one upsert); search quotes the new text |
| 7 | An agent given the base is asked about expenses and about deploys | Its citations name `expenses.txt` and the Deploys page |
| 8 | Python SDK: `ops.raw.kb.sources_source_scopes` with the query "human" | Human Resources |
| 9 | TypeScript SDK: `ops.raw.kb.sources_source_scopes` for the site's libraries and for Confluence spaces | Both libraries under the site; ENG |
| 10 | Console, as James: New knowledge base, Add source, SharePoint and OneDrive; type "human" in the sites picker | Human Resources listed (screenshot `sharepoint-picker-search.png`) |
| 11 | Select all | The site picked; the libraries picker lists Policies Library and Handbook; Select all there picks both (`sharepoint-picker-select-all.png`) |
| 12 | Create and sync | The source's run indexes the libraries' files |
| 13 | A sites search nothing matches, and one Graph refuses | "No site called ..." (`sharepoint-picker-empty.png`); "Couldn't list the sites: ..." (`sharepoint-picker-error.png`) |
| 14 | Add source, Confluence; type "eng" in the spaces picker | Engineering alone listed (`confluence-spaces-picker.png`) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `scripts/test-uc-678-api.py` | passing: 13 checks |
| sdk | `scripts/test-uc-678-sdk.py` | passing: 2 checks |
| ui | `scripts/test-uc-678-ui.mjs` | passing: 9 checks; screenshots in `evidenceDir('uc-678')` |

Run with `OPS_PLUGINS_REPO=<plugins checkout> make usecase-test UC=uc-678 LAYER=<layer>`.

## Gotchas

| Gotcha | Detail |
|---|---|
| A picker lists before it searches | Each picker lists everything the connection reads before a search; a ui step that types before that first list arrives reads the unfiltered answer after its search. The ui script waits for the first list, then for an unmatched row to go |
| Pickers ask every picked value for what it holds | Add source sends each other picker's picks as parents, so the SharePoint scopes tool is asked for a library's contents; it answers nothing for a parent that is not a Graph site id (`<host>,<id>,<id>`) |
| Graph needs a `.sharepoint.com` tenant | The plugin keeps the address its sign-in lookup reads only under `.sharepoint.com` or `.sharepoint.us`, so the fake tenant answers as `contoso.sharepoint.com` |
| Who may read is stored, not shown on the item list | The item list answers `acl: []`; the version's `allowed` is on `GET /v1/items/{id}` |

## Non-vacuous check

Step 4 asserts the second SharePoint sync downloads only the changed file. With a second file (`travel.pdf`) also edited
at the fake before that sync, it failed for the right reason, listing both downloads:
`FAIL 4 the second sync fetches only the changed file, and indexes its new text: {'fetched': ['p2', 'p3'], 'counts':
{'listed': 3, 'unchanged': 0, 'upserted': 2, 'deleted': 1, 'failed': 0, 'skipped': 0}}`. The failure step 2a guards was seen in the
ui layer before the plugin fix: with libraries picked, the sites picker showed "Couldn't list the sites: The picker
could not ask SharePoint and OneDrive: The libraries of site b!policies answered 404 itemNotFound."
