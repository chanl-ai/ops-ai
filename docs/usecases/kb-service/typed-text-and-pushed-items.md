# Typed text and pushed items become cited knowledge

Status: passing. Id: `uc-676`. Service: `kb-service`. Layers: api, sdk, cli, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Add source lists typed text and push as built-in kinds beside files | api | 1 | 1 |
| S2 | A page written as typed text is kept as a file, indexed at once and returned by the agents' search | api | 2, 3 | 3 |
| S3 | Another system pushes items by name: the same item again changes nothing, new content is its next version | api | 4, 5 | 5 |
| S4 | A pushed PDF is read like an upload; a source fed from Files refuses written items | api | 6, 7 | 7 |
| S8 | A pushed web page keeps its address, so its citation links to the page | api | 17 | 17 |
| S5 | A developer pushes an item through the Python and TypeScript SDKs | sdk | 8-10 | 10 |
| S7 | A developer makes a base and a push source and pushes an item with `opsai kb` | cli | 14-16 | 16 |
| S6 | A builder adds a typed text source in the console's Add source and an agent's search cites it | ui | 11-13 | 13 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector | `make db-up` on the pgvector image, or `OPS_PG_PORT=<port>` naming another pgvector server |
| kb-service with its files-service and documents-service | `kb()` in the harness; the ui layer's `withUiStack(..., { platform: true })` |
| A PDF to push | `services/kb-service/seed/pdfs/retail-product-sheet.pdf` |

Run: `make usecase-test UC=uc-676 LAYER=api` (or `sdk`, `cli`, `ui`).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | List source kinds | Built in: `file`, `text`, `push`, each with a manual schedule |
| 2 | Write a page into a typed text source (`POST /v1/sources/{id}/items`) | `created`, indexed, with a file id |
| 3 | Search the base as an agent does (`POST /v1/knowledge-bases/search`) | The page's section, v1 |
| 4 | Push one item twice into a push source | `created`, then `unchanged`; the run count does not move |
| 5 | Push the same name with new content, then search | `updated`, v2; the passage quotes the new text and not the old |
| 6 | Push a PDF as base64 content | Indexed with its page count |
| 17 | Push a `text/html` item with a `url` (run after step 6) | The item is `text/html` with that `url`; the search passage cites the `url` |
| 7 | Write an item into a file source | 400 `source_not_written` |
| 8 | Python SDK: `knowledge.add_base`, `add_source`, then `push` into the push source | `created`, indexed |
| 9 | Python SDK: the same call again | `unchanged` |
| 10 | TypeScript SDK (built from `sdk/typescript`), signed in from the saved profile: `addBase`, `addSource`, `push`, then a search | `created`; the passage holds the pushed text |
| 11 | Console: Add source, pick Typed text, write a title and Markdown | Step 2 shows the title and text fields; no schedule on Review |
| 12 | Create and sync | One `POST /v1/sources` and one `POST /v1/sources/{id}/items`; the item is indexed |
| 13 | Search the base | The passage holds the typed text |
| 14 | `opsai kb create` and `opsai kb add-source`, from a saved profile | A base and a push source, with ids |
| 15 | `opsai kb push` twice | `created`, then `unchanged` |
| 16 | `opsai kb search` | The answer holds the pushed text |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-676-api.py` | passing |
| sdk | `kb-service/scripts/test-uc-676-sdk.py` | passing |
| cli | `kb-service/scripts/test-uc-676-cli.py` | passing |
| ui | `kb-service/scripts/test-uc-676-ui.mjs` | passing |

## Non-vacuous check

Step 4 fails when the route syncs the source for content it already holds: seen red in
`test_a_pushed_item_is_searchable_and_sending_it_again_changes_nothing` (`assert 2 == 1`, the second call started a run)
with the unchanged check removed, then green with it restored.

Step 17 fails when the pushed `url` is not stored: seen red before the change (`item: None`, the passage's `url` None),
then green with it.
