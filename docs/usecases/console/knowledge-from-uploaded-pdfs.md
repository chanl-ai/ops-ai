# A department's PDFs become a cited answer

Status: current. Id: `uc-075`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| kb-service | the ui harness starts it on the run's database |
| platform-service's dev seed | James Richardson; password `northfield-demo` |
| The demo PDFs | `services/kb-service/seed/pdfs/` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates a knowledge base | kb-service answers 201; the maintainers sent is his email, filled in by default |
| 2 | He adds a file source, uploads the branch operations manual into it and syncs | the upload goes to the source's files route (201); the item reads Indexed |
| 3 | He searches the knowledge bases list for it | one row |
| 4 | An agent granted only this base is asked the daily ATM limit; he opens the citation | the popover shows the Branch Operations Manual with page, section and version; Open document shows the PDF and its pages |
| 5 | A second version of the file is uploaded under the same name and synced | the Changes page lists it |
| 6 | Throughout | no knowledge call answers 404 and no page error |

Step 5 uploads through kb-service directly: the source page has no "add files" control on c-056.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-075-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if the file dialog creates the source with no files: no request reaches the source's files route.
