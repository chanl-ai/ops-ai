# A website source keeps a knowledge base current, and answers cite it

Status: current. Id: `uc-674`. Service: `kb-service`. Layers: api.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder adds a website with include and exclude rules, previews what it would fetch, and nothing is stored until it is created | api | 1, 2 | 1 |
| S2 | The first sync takes in the pages the rules and robots.txt allow, and a re-sync fetches only the page that changed | api | 3, 4, 5 | 4 |
| S3 | A page deleted at the site leaves search, at once when its sitemap drops it, after a second miss when it still lists it | api | 6, 6b | 6b |
| S4 | Search runs by meaning and keywords and says so; an agent cites a crawled page, and an agent not given the base cannot search it | api | 7, 8, 9 | 9 |
| S5 | With likely questions and FAQ drafts approved, an approved pair answers its question and cites the passage it came from | api | 10, 11, 12 | 12 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL with pgvector, and OPA | `make db-up` on the pgvector image (`make db-move-image` moves an older stack), or `OPS_PG_PORT=<port>` naming another pgvector server |
| The website plugin | The `ops-ai-plugins` checkout beside this one, or `OPS_PLUGINS_REPO=<path>`; the script loads `plugins/web/src/ops_plugin_web` through `OPS_PLUGIN_PATHS` |
| A help centre to crawl | `docs/usecases/lib/fake_help_site.py`: https as `help.northbank.test` on this machine's private address, with robots.txt refusing `/admin/`, a sitemap index, lastmod dates, ETags, menus and footers around each article |
| Models | models-service's scripted aliases (embeddings on `bank-embed`) and a fake OpenAI with two rules: the questions step and the FAQ drafts step, each answering from the section its prompt names. No provider is called |

Run: `OPS_PLUGINS_REPO=<path> make usecase-test UC=uc-674 LAYER=api`.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Preview the site with include `/lending/**`, `/cards/**` and exclude `/archive/**` | Each page with its outcome: the payment holidays page will be fetched, the archive page is excluded by its rule; no source is stored |
| 2 | Create the source into a new knowledge base | `kind` web, `scopeSummary` help.northbank.test |
| 3 | Sync | Three pages indexed; the excluded page and the robots.txt-refused page are never requested |
| 4 | Change one page and its lastmod, sync again | Only that page is requested; one upserted |
| 5 | Ask about the change | The citation quotes the new text |
| 6 | Delete a page and drop it from the sitemap, sync | It leaves the items and search on that sync |
| 6b | A listed page answers 404 on two syncs | Still there after the first, removed and tombstoned after the second |
| 7 | Read the query's lanes | Keyword and meaning both ran; none skipped |
| 8 | An agent given the base answers in chat | Its citation names the crawled page |
| 9 | An agent not given the base opens a chat on it | Refused: it cannot search that base |
| 10 | Turn on likely questions and FAQ drafts, read the estimate, approve | The estimate counts calls with no model called; the rebuild that follows records model calls |
| 11 | Read the Changes queue | FAQ drafts wait, each with the passage it quotes as `before` |
| 12 | Approve a draft and search its question | The passage returned is matched by the pair (`faq`), on the page it came from, holding the quote |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `kb-service/scripts/test-uc-674-api.py` | passing |

## Non-vacuous check

Step 6b fails when a page that answers 404 once is removed at once, or never. Step 1 failed (503 `preview_failed`)
while kb-service called tools-service with the run environment `production`, which tools-service refuses, so every
plugin call of every app source failed: seen red on the first run of this script, then green once kb-service sent
`live`.
