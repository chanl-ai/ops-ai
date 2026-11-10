# A team takes in SharePoint libraries and Confluence spaces

Status: draft. Id: `uc-678`. Service: `kb-service`. Layers: api, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder picks SharePoint sites, then their libraries, by searching for them in Add source | ui | 1, 2 | 2 |
| S2 | The first sync takes in the picked libraries' files, each kept as a snapshot file with who can see it | api | 3 | 3 |
| S3 | A file changed or deleted in SharePoint is found by the delta query; only the changed file is fetched again | api | 4 | 4 |
| S4 | A builder picks Confluence spaces; an edited page is the only page fetched again | api, ui | 5, 6 | 6 |
| S5 | An agent given the base cites a SharePoint file and a Confluence page | api | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| The plugins | The plugins checkout holding `plugins/sharepoint` and `plugins/confluence`, loaded through `OPS_PLUGIN_PATHS` |
| A SharePoint tenant and a Confluence site | Fakes of Microsoft Graph and Confluence REST served over https on this machine's private address, with the team's connection signed in against them. Not built yet |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Add source, pick SharePoint and OneDrive, search sites for "human" | Human Resources listed, from `POST /v1/sources/scopes` |
| 2 | Pick it; the libraries picker lists its libraries | Policies and Handbook offered; Select all picks both |
| 3 | Create and sync | Every file indexed, each with a file id and its `allowed` ids |
| 4 | Edit one file and delete another at the fake Graph, sync | One file fetched; the deleted one leaves search |
| 5 | Add a Confluence source on space ENG | Its pages indexed |
| 6 | Edit one page, sync | Only that page fetched; search quotes the new text |
| 7 | Ask an agent given the base | Its citations name the file and the page |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | none yet | draft: steps 3, 4 and 6 run today in `services/kb-service/tests/test_connector_plugins.py`, which drives each plugin's own code through the plugin SDK's runner against its fake system, in place of tools-service |
| ui | none yet | draft |

## Non-vacuous check

Not run as a use case. In the kb-service test, step 4 asserts the second sync fetches exactly the changed file: with
the plugin's changes tool withheld it failed (`['p2', 'p3', 'h1'] == ['p2']`, every file listed and fetched again).
Each plugin's own suite was seen red with its delta, tag-match and deleted-facet handling removed.
