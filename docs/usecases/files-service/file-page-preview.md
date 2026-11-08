# A file's page shows its preview or says why not

Status: current on main. Id: `uc-629`. Service: `files-service` with documents-service. Layers: ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin or a viewer opens a PDF or an image and sees its pages, and a text file says to download it, with no outage banner | ui | 1-3 | 1-3 |
| S2 | A file whose stored bytes are gone says so in its preview, and the page around it still works with no outage banner | ui | 4 | 4 |
| S3 | A file not yet read for text is a normal state: no request answers 404 and none is cut short | ui | 1-4 | 1-4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| platform-service, files-service and documents-service | started by the runner's UI stack (`withUiStack`, platform sign-in) |
| People | Priya Shah (admin of `team_ops`) and Ravi Menon (viewer); password `northfield-demo` |
| Files | Uploaded by the script: a PDF, a PNG, a text file and a PDF whose stored object the script removes |

## Steps and expected results

Each step runs as Priya and as Ravi, at 1280 and 390 wide.

| # | Step | Expected |
|---|---|---|
| 1 | Open the PDF's page | Its pages show |
| 2 | Open the image's page | It shows as a page |
| 3 | Open the text file's page | "Preview shows PDFs and images. Download the file to open it." |
| 4 | Open the PDF whose bytes are gone | The preview says the file's content is missing from storage; the name, tabs and fields still show |

Every step: no "can't reach its services" banner, no failed request, no 404 from `/v1/documents/layout`, and no sideways scroll.

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 0 | The script checks it removed exactly one stored object before the walk |
| 1-4 | Failed requests and layout 404s are collected from the browser, not from the page's text |

## Scripts

| Layer | Script |
|---|---|
| ui | `docs/usecases/files-service/scripts/test-uc-629-ui.mjs` |
