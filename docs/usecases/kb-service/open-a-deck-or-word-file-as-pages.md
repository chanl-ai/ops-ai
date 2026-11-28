# Open a deck or Word file as pages

Status: passing. Id: `uc-951`. Service: `kb-service`. Layers: api, cli, ui.

Short title: Open a deck or Word file as pages

## Story

As a knowledge owner checking what an answer was built from, I want a slide deck or Word file to open as pages beside
its text, like a PDF, so that a slide that is only a picture is described and cited, and choosing a paragraph shows me
the slide or page it came from.

## People

| Person | Role | Does what |
|---|---|---|
| Maya | builder | Adds a project-update deck and a decision note to a push source and opens each one |
| William | platform admin | Turns on sending page pictures to a model for the team |
| Priya Shah | admin | Opens the deck and checks the described slide |
| Ravi | viewer | Opens the same deck to read it |

## In this example

Maya adds two files from a claims intake project: a three-slide project update whose second slide is only the
architecture diagram, and a two-page decision note. The converter worker is running and documents-service is pointed at
it (`OPS_DOCUMENTS_CONVERTER_URL`). It assumes the team's pageImages policy is on and the model alias `extract` may see
pictures; the fake model describes each picture the same way. The command-line step runs with no converter, to show a
deck still gives its text.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The deck's picture slide is described by a model, marked so, and a question cites slide 2 | api | 1 | 1 |
| S2 | Each block of the deck is boxed as its whole slide, and the text names the drawn PDF | api | 2 | 2 |
| S3 | Slide 2 is served as a picture drawn from the deck's PDF | api | 3 | 3 |
| S4 | Each paragraph of the Word note sits on the page it is drawn on | api | 4 | 4 |
| S5 | With no converter, `opsai kb text` still prints the deck's text | cli | 5 | 5 |
| S6 | Priya opens the deck, turns to slide 2, sees it read by a model, chooses its description and sees the whole slide highlighted; Ravi sees the same | ui | 6-7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector, OPA | `make db-up` |
| The converter worker | `make converter-up` (port 8780 + offset), or `OPS_DOCUMENTS_CONVERTER_URL` |
| kb-service, files-service, documents-service, platform-service, models-service with the fake OpenAI | the harness's `kb()`, `platform()`, `models()`, `fake_openai()` |
| For the ui layer: a stack started with `make up CONVERTER=1` | the console at `OPS_CONSOLE_URL` |

Run: `make usecase-test UC=uc-951 LAYER=api`.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Push `project-update.pptx` and read `GET /v1/items/{id}/text` page by page; ask the base what sends work to the Intake service | Slides 1 and 3 read by text, slide 2 by a model; slide 2's one block is the model's description; a citation in the first three is at page 2 |
| 2 | Look at the deck's blocks | Each has one box, its whole slide; `renditionId` names a file other than the deck |
| 3 | `GET /v1/documents/readings/{fileId}/pages/2/image` | A PNG of slide 2 |
| 4 | Push `decision-note.docx` (a page break between its two paragraphs) and read its text | Two pages; the decision on page 1, the risks on page 2, each boxed as its whole page |
| 5 | With no converter, push the deck and run `opsai kb text <item>` | `[p1 text] The event queue went live…` and `[p3 text] Replay after an outage…`: the text, with no drawn pages |
| 6 | Open `/data/knowledge/documents/{id}` for the deck | The drawn slides show on the left, `Page 1 of 3` |
| 7 | Turn to page 2 and choose the model's description | Read by shows A model; the whole slide is highlighted and the description is pressed; the same as a viewer |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-951-api.py` | passing |
| cli | `kb-service/scripts/test-uc-951-cli.py` | passing |
| ui | `kb-service/scripts/test-uc-951-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails with page sources `[text, none, text]` and step 2 with `renditionId` null when documents-service is started
without `OPS_DOCUMENTS_CONVERTER_URL`; seen red by running the api script with `documents_env` left out.
