# Knowledge base

Status: current design, 2026-11-11. Code cited at commit 81c9883a. This page covers how content gets into a knowledge
base from many kinds of source, how it is cleaned, split, enriched and embedded, and how agents search it by meaning
and by words, marking what is built and what is not.

Service facts (every route, request field and error code) live in [kb-service](../services/kb-service/overview.md),
and this page links to it instead of repeating them. Table layout is in [data](data.md) and
[data model](data-model.md); the meaning-lane threshold calibration is in
[meaning threshold](../services/kb-service/experiments/meaning-threshold.md).

## Status by part

| Part | Built | Where |
|---|---|---|
| Bases, sources, items, versions, pieces, changes, runs; team isolation | Built | `services/kb-service/src/ops_kb/store/knowledge.py`; migrations kb_0001 to kb_0024 |
| Source kinds file, text, push, tool; website sources as plugin sources | Built | `services/kb-service/src/ops_kb/service.py:101`; `source_settings.py:72-73` |
| Source kinds listed by the API, so the console keeps no list of its own | Built | `services/kb-service/src/ops_kb/app.py:617` |
| Settings per source for every stage, validated on save | Built | `source_settings.py`; migration `0015_source_settings.py` |
| OCR mode per source, environment default `auto` | Built | `source_settings.py:36`; `packages/ops_service_kit/src/ops_service_kit/settings.py:236` |
| Every plugin item kept as a `knowledge_snapshot` file before it is read | Built | `services/files-service/src/ops_files/models.py:24` |
| Index units apart from cited pieces | Built | migration `0016_index_units.py` |
| Embeddings through models-service, pgvector store, HNSW index | Built | `services/models-service/src/ops_models/app.py:842`; `packages/ops_service_kit/src/ops_service_kit/model_calls.py:122`; migration `0021_unit_vectors.py`; `store/vectors.py` |
| Hybrid search, reciprocal rank fusion, per-lane floors, lanes reported | Built | `retrieval.py:21-23`, `:75-76`; `search.py:35`, `:50-65` |
| Rerank and rewrite around the search | Built | `query_steps.py:18`, `:119` |
| Likely questions and FAQ drafts with approval, estimate and ceilings | Built | `source_settings.py:61`; `service.py:2782`; `app.py:498-509`, `:572-600` |
| One schedule rule for every source kind | Built | `packages/ops_store/src/ops_store/schedule.py:21`, `:92` |
| Health, tombstones, failing alert event | Built | `store/knowledge.py:197`; `service.py:186`; `app.py:489-497` |
| Plugin contract: list, get, changes, deleted, scopes, preview, allowed | Built | `packages/ops_plugin_sdk/src/ops_plugin_sdk/manifest.py:343-345`; `tool_sources.py:601` |
| Contract test any knowledge-source plugin must pass | Built | `packages/ops_plugin_sdk/src/ops_plugin_sdk/testing.py:179` |
| Website, SharePoint and Confluence plugins | Built, not run against a real tenant | pinned in `deploy/plugins.json` |
| An agent searches only its own bases, unless its "all team knowledge bases" option is on | Built | `packages/ops_agent_kernel/src/ops_agent_kernel/kernel.py:83`, `:631-635` |
| A base's settings in five sections, each patched alone and checked whole; presets fill them all | Built | `schemas.py` (`RetrievalSettings` to `SourceDefaults`); `service.py` (`settings_of`, `settled`, `PRESETS`); migration `0024_base_settings.py` |
| A pushed item's `url`, cited by search | Built | `schemas.py` (`WrittenItemIn.url`); `service.py` (`put_item`) |
| The base's answer settings read by the kernel | Built | every search answer carries each base's `answer` section; the kernel replaces an uncited answer, or a turn that found nothing, with the first withholding base's no-answer message (`packages/ops_agent_kernel/src/ops_agent_kernel/kernel.py` `_base_withholds`); a pieces-only base never withholds |
| The base's sync settings applied by syncs, the strictest of the bases a source feeds winning | Built: a changed version held for review, removed items kept and flagged, the failing alert turned off | `service.py` (`sync_rules`, `_hold`, `_apply_held`, `settle_run`); `tool_sources.py` (`_flag_removed`) |
| Stale after a number of days read by freshness | Designed, not built yet | served on the source detail; freshness still follows the schedule |
| A new source copies its base's source defaults | Built | `service.py` (`create_source`, `_base_split`) |
| JavaScript pages rendered in a headless browser worker | Designed, not built yet | |
| An answer with no cited passage withheld, on by default | Built | on in the Balanced and Precise presets, off in Search only; applies whether or not the agent's own end check is on |
| Playground answer written by a kernel turn | Designed, not built yet | the query route returns passages only (`service.py:1834-1837`) |
| Filters on collection, source, tags and metadata applied to search, each base its own, in both lanes; a per-request collection | Built | `retrieval.py` (`Scope`); `store/fulltext.py` (`scope_sql`); `store/vectors.py` (`nearest`); `schemas.py` (`SearchIn.collection`) |
| Filters from conversation variables; freshness and trust boosts | Designed, not built yet | |
| Keyword lane on the shared `ops_store.dialect.full_text` | Designed, not built yet | the lane has its own PostgreSQL query (`store/fulltext.py:1-2`) |
| Search on SQL Server | Designed, not built yet | |
| Who-can-see enforced per item | Designed, not built yet | stored, not enforced |
| Query log, unanswered list, gap job, evals over retrieval | Designed, not built yet | |
| Draft then publish for knowledge content | Designed, not built yet | |
| Schedules on the shared job runner | Designed, not built yet | |

## The pipeline

Every source kind follows one path. Only the first two steps differ between a web page, a SharePoint file and an
upload.

```
source → fetch → snapshot → read → clean → split → enrich → embed → index → search → answer
```

| Stage | What happens | Owner |
|---|---|---|
| Source | A team says what to bring in, how often, and how to treat it | kb-service `kb_sources`, with a settings column |
| Fetch | Get each item's bytes, or learn it has not changed | the source's plugin, called through tools-service (egress check and call log apply) |
| Snapshot | Keep the fetched bytes once, as a file | files-service, purpose `knowledge_snapshot` |
| Read | Turn a file into pages, text, headings, tables and form fields | documents-service reading step; kb-service parses no bytes |
| Clean | Drop page furniture, boilerplate and repeats; normalise text | `ops_ingest` clean strategy, applied per source |
| Split | Cut the reading into pieces a search can return | `ops_ingest.split`, applied per source |
| Enrich | Write likely questions per piece; draft question-and-answer pairs | `ops_ingest.split` AI steps, through `ops_service_kit.model_calls` |
| Embed | Turn each index unit into a vector | models-service, through `model_calls` |
| Index | Store what is searched, pointing at what is cited | kb-service `kb_units`, `kb_unit_vectors` |
| Search | Find the best pieces for a question | kb-service, behind the Retriever port |
| Answer | Write the answer from the pieces, with citations, or withhold it | the agent kernel |

Because every item has a snapshot, a re-index never fetches from the web or the app again.

## Data model

| Table | What it holds | Built |
|---|---|---|
| `kb_bases` | A knowledge base, its owner, team and retrieval settings | Yes |
| `kb_sources` | A source, its kind, `settings` (every stage's settings) and health | Yes |
| `kb_base_sources` | Which bases read which sources | Yes |
| `kb_items`, `kb_item_versions` | Items and their versions; `indexed_with` is the digest of the settings an item was built under | Yes |
| `kb_chunks` | Pieces, the unit a search returns and an answer cites | Yes |
| `kb_units` | Index units of a piece: its own text with context header, its children, its likely questions, its approved FAQ pairs; full-text vector | Yes |
| `kb_unit_vectors` | Each unit's embedding, with the model and width it was made with (PostgreSQL with pgvector) | Yes |
| `kb_changes` | Version replacements and FAQ drafts awaiting review | Yes |
| `kb_runs` | Each sync or rebuild run with counts and model spend | Yes |
| `kb_outbox` | Audit entries and events, delivered by a relay | Yes |
| `kb_queries` | Each question, masked: rewrite, lanes run, top score, answered or withheld and why, pieces cited; kept 90 days | No |

## Settings of a base

A base's settings are five sections. `PATCH /v1/knowledge-bases/{id}` takes any of them; the keys sent change and the
rest of that section and the other sections stay. A key a section does not keep, or a value out of range, is 400
`invalid_settings`, so no caller saves a value nothing reads. Retrieval sits in the base's `retrieval` column, the
other four in its `settings` column (kb_0024); null reads as the defaults.

| Section | Holds | Default | Who reads it |
|---|---|---|---|
| `retrieval` | Mode, weight, rerank, rewrite and its instruction and model, pieces returned, keyword and meaning floors; the scope (`scopeCollections`, `scopeSourceIds`), `tagsInclude`, `tagsExclude`, `includeUntagged`, metadata `filters` | Hybrid, 0.6, 8 pieces, floors 0.5 and 0.38, no scope | The search: both lanes keep each base's pieces within its scope (`store/fulltext.py` `scope_sql`) |
| `answer` | `shape` (`answer_with_citations` or `chunks`), `withholdUncited`, `noAnswerMessage` | An answer with citations, withheld when uncited | The query route's no-answer message; the agents kernel, from `answers` in each search answer |
| `sync` | `changes` (`apply` or `review`), `removedAtSource` (`remove` or `keep`), `staleAfterDays`, `notifyOnFailure` | Apply, remove, 365 days, notify | Syncs of every source the base reads; served as `automation` (`act` or `suggest`). `staleAfterDays` is served, not yet read by freshness |
| `access` | `mcp.enabled`, `mcp.toolName` | Off, `search_<slug>` | Nothing yet; the MCP search tool is not built |
| `sourceDefaults` | How a new source splits: `strategies`, `size`, `overlap`, `childSize`; AI steps are refused here and set per source with their estimate | At headings with context headers, 400 tokens, overlap 40 | A new source created into the base copies the values that differ from the defaults; each source keeps its own copy |

A base is searchable by its whole team; no narrower list of people is kept, and `access.members` is always
`{"mode": "all"}`. The model, temperature, length and instructions of an answer belong to the agent, so a base does not
keep them, nor `reranker`, `expandCount`, `asOf`, `structuredTables`, `citationStyle` or `includeChunks`. A base saved
before kb_0024 keeps those keys in its row until its next save; they are left out when read, and its answer shape and
no-answer message carry over into `answer`.

A preset given at create (`balanced`, `precise`, or `raw`, shown as "Search only") fills every section; the values a
create sends override it, and any later patch wins. The base does not record which preset it started from.

| Preset | Pieces | Keyword floor | Meaning floor | Gives back | Withholds uncited |
|---|---|---|---|---|---|
| `balanced` | 8 | 0.50 | 0.38 | Answer with citations | Yes |
| `precise` | 5 | 0.65 | 0.45 | Answer with citations | Yes |
| `raw` (Search only) | 10 | 0.40 | 0.30 | Pieces only | No |

When a source feeds several bases, its syncs follow the strictest of their sync settings: review over apply, keep over
remove, the fewest days to stale, and the failing alert sent when any base asks. A held version waits in Changes as a
pending change from the source's sync; search serves the current version until it is approved
(`POST /v1/knowledge-changes/decide`), and the same content found again, waiting or rejected, is not held twice. A
removed item that is kept stays searchable and carries a warning saying its source removed it.

A pushed item (`POST /v1/sources/{id}/items`) may carry the `url` it lives at, such as a web page's address; the item
and every passage cut from it cite that `url`.

## Settings per stage

Each setting lives in the source's settings, is validated when saved (400 `invalid_settings`), and is applied by the
stage that owns it. A changed setting is compared with each item's `indexed_with`, and the re-index table below says
what runs again.

### Fetch, for web pages

The website plugin lives in the plugins repository and is pinned in `deploy/plugins.json`; its code is not in this
repository. Built here means confirmed by the plugin guide (`docs/guide/plugins.md:470-472`) or by kb-service's own
code. Rows marked "In the plugin" are the designed values, which the plugin owns and this page has not checked at
this commit.

| Setting | Options and default | Built |
|---|---|---|
| Start | One URL, a list, or a sitemap; `/sitemap.xml` and robots.txt `Sitemap:` lines found from a start URL; sitemap indexes followed one level | Yes (sitemaps and links) |
| Include and exclude | Path patterns; exclude wins | Yes (kept in the source's `config.values`) |
| Follow links | Off, or depth 1 to 5 (default 2), same host only; linked pages still pass the rules | In the plugin |
| Max pages | 1 to 5,000, default 500; a run says when the cap stopped it | In the plugin |
| robots.txt | Always obeyed for `OpsAI-Knowledge` and `*`; no setting turns it off | Yes |
| Rate | 1 request a second per host, 0.2 to 5; a slower `Crawl-delay` wins; 429 and 503 back off with `Retry-After` | Yes (one a second, crawl delay, resume after a rate limit) |
| Render JavaScript | Off by default, on per source, in a separate browser worker used only by this plugin | No; the preview flags pages that show their text only with JavaScript |
| Sign-in | None, or a header or cookie from the team's connection; secrets stay in tools-service | In the plugin |
| Allowed hosts | The start URLs' hosts only; a new host waits for an admin under the account's new-hosts policy (409 `host_waiting`); private and link-local addresses refused unless allowed by name | Yes for host approval (`service.py:1008`); address refusal in the plugin |
| Preview | First 50 matched URLs, pages skipped and why, page count; nothing stored | Yes (`app.py:477`) |

### Read, clean, split, enrich

| Stage | Setting | Default |
|---|---|---|
| Read | OCR: off, auto, always | The environment's `kb_ocr` (`auto`) |
| Clean | Page furniture | On for web and connector sources, off for files |
| Clean | Main content only | On for web |
| Clean | Lines repeated across more than half a site's pages | On for web |
| Clean | Duplicates: flag or skip | Flag: search returns only the newer copy |
| Clean | Normalise (NFKC, invisible characters, whitespace) | Always |
| Split | Preset: policy manual, help centre, rate table, email templates, custom | Help centre for web; headings with context headers for files |
| Split | Piece size 100 to 2,000 tokens, overlap below the size | 400 and 40 |
| Split | Parent and child; table rows; context headers; keep as one piece | Per preset |
| Enrich | Likely questions, 1 to 5 per piece | Off; 3 when on |
| Enrich | FAQ drafts, up to 8 pairs per section | Off |
| Enrich | Model | The `bank-standard` alias |
| Enrich | Ceiling | $5 per run (`aiCeiling`, 0.1 to 500); $50 per environment per day (`kb_ai_daily_cap`) |

AI steps write nothing until the base's owner approves them as chosen; an AI step added later is pending again. The
estimate splits up to 20 items with no model call and scales calls and tokens to the source. Past a ceiling, or with
the model down, the remaining pieces are indexed without questions and the run says why. Only pieces whose digest
changed are enriched again.

### Re-index

| Setting changed | What runs |
|---|---|
| Retrieval | Nothing |
| Embedding model or width for the environment | Embed again; read nothing |
| Questions or FAQ drafts turned on, or their model | Enrich and embed the new units only |
| Split | Split again from the stored reading, enrich changed pieces, embed |
| Clean | Clean from the stored reading, then as split |
| OCR mode, or a new reader version | Read the snapshot again, then as clean |
| Fetch settings | The next sync fetches what the new rules allow and removes what they exclude |

A rebuild runs in the background under the source's lease, reports progress in its counts and can be cancelled
(`app.py:611`).

## Schedules and change tracking

One rule decides when any source is due (`packages/ops_store/src/ops_store/schedule.py:92`), in the schedule's IANA
time zone, UTC when left out.

| Schedule | Default for |
|---|---|
| Manual | Files |
| Every 1, 2, 4, 6 or 12 hours | none |
| Daily at a time | Web, 02:00 UTC (`source_settings.py:109`) |
| Weekly on a day and time | Connectors use their manifest's schedule |

| Source | Change check, cheapest first | Cost of an unchanged item |
|---|---|---|
| Web with a sitemap | The sitemap's lastmod against the stored one | No page request |
| Web, every page | Conditional request with ETag or If-Modified-Since | One 304 answer |
| Web, no headers | Fetch, read, clean, compare the cleaned digest | One fetch and read; no split, no model call |
| Connector | The contract's `changes` with a cursor | Not listed |
| Any item | The piece digest after splitting | Unchanged pieces keep their questions and vectors |

Deletes: a web item that answers gone on two syncs in a row, or that leaves the sitemap and the rules, is removed and
its address tombstoned so a link elsewhere does not bring it back; a person can lift a tombstone. Connectors report
deletes through `deleted`, with a weekly full listing as a safety net. A removed item leaves search at once; its
snapshot is released and files-service keeps it 30 days more unless a legal hold keeps it longer.

Health per source: last good sync, days failing, runs failing in a row, needs reconnect, tombstone count; a status
and reason per item; each run's trigger, counts and model spend. The second failed run in a row writes
`knowledge.source.failing`, which reaches agents-service's events so a workflow can notify the source's owner.

## Source plugin contract

A connector is a plugin; a new one needs no kb-service code. kb-service owns the sync loop, snapshots, versions,
deletes and the schedule; a plugin owns only how to talk to its system.

| Role | Manifest tool | Returns | Required |
|---|---|---|---|
| List | `list` | Items with id, title, url, modified time, folder path and a version tag, paged by cursor | Yes |
| Fetch | `get` | Bytes, type, metadata and allowed principals; or `unchanged` when the version tag matches | Yes |
| Changes since | `changes` | Items added or changed since a cursor, and the next cursor | No; without it each sync lists everything |
| Deleted | `deleted` | Ids removed since a cursor | No; without it the weekly full listing finds deletes |
| Who can see | `allowed` on each fetched item | User and group ids from the source system | No; stored per item version, not enforced while access is team-wide |
| Pickers | `scopes` | Sites and libraries, or spaces, searched by name, for Add source | No |
| Preview | `preview` | What a source would take in; nothing stored | No |

| Plugin | Lists | Changes since | Who can see |
|---|---|---|---|
| `opsai.web` | Sitemaps, start URLs and links, after rules and robots.txt | Sitemap lastmod and conditional requests | None (public, or one sign-in) |
| SharePoint and OneDrive | Picked sites, libraries and folders through Microsoft Graph | Graph delta query per drive | Item permissions from Graph |
| Confluence Cloud and Data Center | Picked spaces' pages and attachments | CQL lastmodified after the cursor | Space and page restrictions |

## Retrieval

One search in kb-service serves every caller: grounding on each turn, the `search_knowledge` tool, the workflow
Knowledge step, the Playground and the query route. The base's retrieval settings decide how many pieces return; a
caller's `limit` only caps it (`service.py:2850-2866`).

| Part | How it works | Default | Built |
|---|---|---|---|
| Keyword lane | A unit scored by the share of the question's terms it holds, with at least two shared terms when the question has two | Floor 0.5 | Yes, PostgreSQL only |
| Meaning lane | The question embedded with the environment's model, compared by cosine similarity in pgvector with an iterative HNSW scan | Floor 0.38 (0.45 precise, 0.30 raw) | Yes |
| Fusion | Reciprocal rank, k = 60, weighted toward meaning; a lane that returned nothing is not fused | Weight 0.6 | Yes |
| Units to pieces | A matching child, question or FAQ unit returns its piece once, naming the unit that matched | Always | Yes |
| Limit | Pieces per answer; at most 2 from one item | 8 | Yes |
| Lanes reported | Lanes asked, run and skipped with the reason (`no_embedding_model`, `no_vector_store`, `no_vectors`, `no_candidates`, `embedding_unavailable`, `no_full_text`); `/health` counts units not embedded | Always | Yes |
| Rewrite | A model rewrites the question with the base's instruction; before and after returned | Off | Yes, with an instruction; templates with variables not built |
| Rerank | A model scores the top 20 fused pieces from 0 to 10 | Off | Yes |
| Filters | Collection, source, tags in and out, untagged, metadata conditions (`is`, `is_not`, `one_of`, `before`, `after`, `exists`, compared as text), in both lanes, per base; a request may add one collection; later from conversation variables | None | Yes |
| Freshness and trust | A verified item raised a little; an item from a source failing 7 days or more lowered a little; nothing excluded | On | No |

Several bases in one search use every lane any asks for, the lowest thresholds, the mean weight and the largest limit.
Rerank and rewrite run through models-service on the base's `queryModel` alias or the environment's `kb_query_alias`
(`bank-standard`); a step whose model cannot answer leaves the search as it would have been and says why, so a search
never fails because a model did.

Embedding settings, one model per environment:

| Setting | Default | Rule |
|---|---|---|
| `OPS_EMBEDDING_ALIAS` | `bank-embed` | Every unit embedded with it |
| `OPS_EMBEDDING_WIDTH` | 1536 | Refused at start above 1,998 (`settings.py:39`, `:483-488`), the pgvector HNSW limit |

A model or width change embeds every unit again and reads no file again. Units a sync could not embed are picked up
by the `kb_embed` background process (`embedding.py:119`).

Answers are written by the kernel. While a search runs, the kernel sends a `retrieving` status
(`kernel.py:977`) that voice and chat agents speak as "checking our documents". Every caller gets one passage shape:
heading path, page, version, url, verified, the snapshot's file id, and "read by OCR" when the page's OCR confidence
is low. The designed grounding rule withholds an answer with no passage above the threshold or with no citation, and
shows the reason; it is not built.

## FAQs

| | Likely questions | FAQ drafts |
|---|---|---|
| What the model writes | 1 to 5 questions a piece answers | Question-and-answer pairs per section, up to 8, each quoting the exact words it came from; a pair quoting text not in its section is dropped |
| Stored as | `kb_units` of kind `question`, pointing at the piece | A change with origin `generated_faq`; on approval a unit of kind `faq` of the piece holding its quote |
| Review | None; questions help search and never reach the answer | Approve, edit or reject, one or many, in the Changes queue beside the source passage |
| Search returns and cites | The piece | The source passage, with the approved question as its best match |
| When it runs | At sync, for pieces whose digest changed | At sync, for sections whose text changed; their pending drafts are superseded and approved pairs marked `source_changed` |

The Changes queue is the one place knowledge content is reviewed; FAQ drafts are one origin there.

## Quality loop

Designed, not built yet.

| Part | What it does | Owner |
|---|---|---|
| Query log | `kb_queries`, kept 90 days | kb-service |
| Stats | Answer rate, withheld rate, use per source and per item, on the base's Overview | kb-service |
| Unanswered list | Questions withheld or below the threshold, grouped by meaning, with a count each | kb-service |
| Gap job | Nightly, per group: a new item, an edit, a duplicate to merge, or a contradiction, each as a draft in the Changes queue | a job on the one schedule rule |
| Evals | A question set per base with expected items: hit at 5, mean reciprocal rank and faithfulness per settings version; the judge sees each turn's question and the pieces used | the platform eval runner |

## Add source in the console

Three steps at one width, with the footer pinned while the body scrolls: Source (with an inline connect when the app
is not connected), What to include (scope, include and exclude rules, live preview), and Review (schedule, the
questions and FAQ drafts switches with the cost estimate, the defaults, an Edit link per section, and Create and
sync). There is no Save draft; closing with changes asks first. Reading, cleaning, splitting and metadata take their
preset's defaults and are changed later on the source's Settings. After Create and sync a toast offers View source,
the first sync starts at once and its progress shows on the Sources tab.

## Scale and cost

Basis: 300 new or changed documents a day, 8 pages each, so 2,400 pages; 700 to 1,500 tokens a page; 400-token
pieces, so 4,800 to 9,600 pieces a day; 500 to 5,000 questions a day. Prices are list prices and need a check before
budgeting.

| Item | Billed or used | Low a day | High a day |
|---|---|---|---|
| Embeddings | Model tokens | $0.04 | $0.60 |
| Likely questions, on for every source | Model tokens | $0.53 | $11.50 |
| FAQ drafts, on for every source | Model tokens | $0.35 | $10.80 |
| Rerank | Model tokens per question | $0.50 | $35 |
| Query embedding and rewrite | Model tokens per question | under $0.01 | $0.40 |
| Crawl, plain pages | Service CPU; a 2,000-page site checked daily at 1 request a second takes about 33 minutes | $0 | $0 |
| Crawl, rendered pages | 2 to 6 seconds and 200 to 300 MB per page; shows as machine size | $0 | $0 |
| Snapshots | Storage: 20 to 200 KB a page, 0.5 to 5 MB an attached document | 6 MB | 600 MB |
| Vectors | 1,536 dimensions at 4 bytes, before the HNSW index (1.5 to 2 times more) | 30 MB | 240 MB |

With every switch on, model spend is about $1.40 to $58 a day; with the defaults (questions, drafts and rerank off),
about $0.05 to $1 a day. Each run records its real spend.
