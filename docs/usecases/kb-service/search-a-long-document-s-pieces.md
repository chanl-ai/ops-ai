# Search a long document's pieces on the server

Status: passing. Id: `uc-772`. Service: `kb-service`. Layers: api.

Short title: Search a long document's pieces on the server

## Story

As a builder checking what a knowledge base holds, I want to search a long document's pieces so that I find the one I need without the browser loading the whole document.

## People

| Person | Role | Does what |
|---|---|---|
| Maya | builder | Writes a handbook into a typed text source and searches its pieces |

## In this example

In this example Maya writes a six-section servicing handbook and searches its pieces for escrow. It assumes a knowledge base and a typed text source, both made in the steps.

## Stories

Four or five things a person does and sees work, in plain words, each on one layer. Its steps are rows of the steps
table below, and "Proved by" is the one step whose check shows the story works. A script names each check by its step
("2 the hold is placed"), so a run reports each story as works or broken, with the step that failed.

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Maya opens a document's pieces and they arrive a page at a time, in reading order | api | 1 | 1 |
| S2 | Maya searches the pieces and the server answers only the matching ones, paged | api | 2 | 2 |
| S3 | A document id the team cannot see has no pieces | api | 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector | `make db-up` |
| kb-service with its files-service and documents-service | `kb()` in the harness |

Run: `make usecase-test UC=uc-772 LAYER=api`.

## Steps and expected results

Each step is something a person does through the public SDK, the CLI or the console. A step the product cannot do yet
stays in the table as **Open**, and a card is filed for it; the script never reaches around the product with a helper.

| # | Step | Expected |
|---|---|---|
| 1 | Read `GET /v1/items/{id}/chunks` with no search | Every piece, in reading order, with `pagination.total` |
| 2 | Read it with `search=escrow`, one piece a page, then page 2 | Only the two escrow pieces, `hasNext` on the first page |
| 3 | Read the pieces of an id the team does not hold | 404 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-772-api.py` | passing |

## Non-vacuous check

Step 2 fails when the store's search columns are dropped: the kb-service test `test_a_documents_pieces_are_searched_and_paged_on_the_server` was seen failing that way (total 3, want 2).
