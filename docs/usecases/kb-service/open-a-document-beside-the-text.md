# Open a document beside the text read from it

Status: passing. Id: `uc-950`. Service: `kb-service`. Layers: api, cli, ui.

Short title: Open a document beside the text read from it

## Story

As a knowledge owner checking what an answer was built from, I want to open a document beside the text read from it so
that I can see which words came from the page, which a model wrote from a picture, and which pages were not read.

## People

| Person | Role | Does what |
|---|---|---|
| Maya | builder | Adds a review PDF with a diagram page, a Word note and a deck of pictures, and opens each one |
| William | platform admin | Turns on sending page pictures to a model for the team |

## In this example

In this example Maya adds three files from a claims intake project to a push source: a two-page architecture review
whose second page is a diagram with no text, a decision note written with bold lines instead of heading styles, and a
22-page deck of pictures. It assumes the team's pageImages policy is on and the model alias `extract` may see pictures;
the fake model describes each picture the same way.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Maya opens the review and the diagram page has a description marked as written by a model, and a question cites page 2 | api | 1 | 1 |
| S2 | Each paragraph of the review knows where its lines sit on its page | api | 2 | 2 |
| S3 | The Word note shows its four sections | api | 3 | 3 |
| S4 | The deck stops at 20 described pages and says the rest were not read, and why | api | 4 | 4 |
| S5 | Maya reads the review's text from the command line | cli | 6 | 6 |
| S6 | Maya opens the review in the console, chooses a paragraph and sees its lines lit on the page, then chooses a line and sees its paragraph selected | ui | 7-8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector, OPA | `make db-up` |
| kb-service, files-service, documents-service, platform-service, models-service with the fake OpenAI | the harness's `kb()`, `platform()`, `models()`, `fake_openai()` |

Run: `make usecase-test UC=uc-950 LAYER=api`.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Push `architecture-review.pdf` (a text page, then a picture-only page) and read `GET /v1/items/{id}/text` page by page (`?page=2` for the second); ask the base what sends work to the Intake service | Page 1 is read by text, page 2 by a model; page 2's one block is the model's description with a whole-page box; a citation in the first three is at page 2 |
| 2 | Look at page 1's paragraph | It has one box per line, all on page 1 |
| 3 | Push `decision-note.docx` and read its text | Four sections: Decision, What we did not choose, Who does what, Open risks; no page boxes |
| 4 | Push a 22-page picture deck and read its text | Pages 1 to 20 read by a model, 21 and 22 not read, one note: "Pages 21 to 22 were not read. Not described: this file reached its limit of 20 pages read by a model." |
| 5 | Ask for an item the team does not have | 404 |
| 6 | `opsai kb text <item>` on a two-page PDF | The heading as `# Claims intake review`, then `[p1 text] The event queue went live…` and `[p2 text] Replay after an outage…`: every page, though the service answers one at a time |
| 7 | Open `/data/knowledge/documents/{id}` and choose the first paragraph | The paragraph is pressed and its lines are highlighted on page 1 |
| 8 | Choose a highlighted line on the page | Its paragraph is the one pressed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-950-api.py` | passing |
| cli | `kb-service/scripts/test-uc-950-cli.py` | passing |
| ui | `kb-service/scripts/test-uc-950-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails with `[text, ocr]` or `[text, none]` page sources when documents-service's picture reading is not wired
(`readings.pictures` unset in `ops_documents/__main__.py`), and its citation check fails at page 1 when kb-service does
not break a section at a model page (`SectionBuilder.break_at`); the second was seen red in `tests/test_item_text.py`.
