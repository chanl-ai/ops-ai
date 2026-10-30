# kb-service

Status: first slice built, 2026-10-15; checked 2026-10-16. `services/kb-service` (`ops_kb`), on :8740, with its
own migration chain (`alembic_version_kb`, kb_0001 to kb_0004). Tests: `services/kb-service/tests`. Designed surface:
this page section 6. Use case: uc-080
(`docs/usecases/kb-service/knowledge-cited-answers.md`).

## What it does

A department uploads text PDFs (or markdown and text files) into a file source, a knowledge base reads that source,
and an agent granted the knowledge base cites passages from it by document, version, page and section.

| Part | Detail |
|---|---|
| Knowledge bases | Created with a required owner (`collection_without_owner`), named uniquely per tenant, optionally under a caller-chosen id (`kb_[a-z0-9_]+`). Listed and paged on the server with the console's `page`, `pageSize` and `search` |
| Sources | File sources only (`type_unsupported_in_phase` otherwise). A source holds file ids. Files are uploaded to files-service first; `POST /v1/sources/{id}/files` {fileIds} adds them, each the team's and scanned clean, and records a reference so Files keeps it while the source reads it. `POST /v1/knowledge-bases/{id}/documents` {fileIds} is the console's one-click Add documents: it makes or reuses the base's documents source, found by the id the base records (`kb_bases.documents_source_id`, so a rename never makes a second one), adds the files through the same check and syncs. Both routes refuse the same files (`test_both_add_routes_refuse_the_same_files`), and a refused batch releases the Files references it took for the ids before the refused one. kb-service writes bytes itself only for pasted pages and the dev-start seed |
| Sync | `POST /v1/sources/{id}/sync`, body `{full?, retry?}` and nothing else (400 for an unknown field). Each file is parsed and split with `ops_ingest` (headings become sections, chunks carry page and section). A new name is a new document; a known name with new content is its next version, written with its chunks in the transaction that withdraws the old version's chunks and records a change row. `full` and `retry` rebuild documents from the same content under their current version. A PDF with no text layer fails that document with `no_text_layer`; the rest index. Every sync is a run (`/v1/sources/{id}/runs`, `/v1/sync-runs/{id}`) |
| Retrieval | A `Retriever` port (`retrieval.py`) with one adapter, Postgres full-text (`store/fulltext.py`): a chunk is scored by the share of the question's terms it holds; below half (and below two shared terms when the question has two) nothing is returned, so an unanswered question gets no passage rather than a weak one. K12 `POST /v1/knowledge-bases/{id}/query` (409 `not_indexed` before any sync) for the console; M1 `POST /v1/knowledge-bases/search` for agents-service, tenant from its service token |
| Changes | `GET /v1/knowledge-changes` lists who replaced which document, from and to which version, with the first changed section before and after |
| Team | A base, a source and everything under them (links, documents, versions, chunks, changes, runs) belong to one team, and the database holds every kb transaction to it (kb_0011, role `ops_kb_tenant`). A base's name is unique in its team; an id another team holds answers 409 with no team named. "Used by" names and counts the acting team's agents only | `store/knowledge.py`, `tests/test_kb_isolation.py`, an earlier change |
| Who may change what | A knowledge base: its owner or a tenant admin (update, attach and detach, refresh, delete). A source: its owner or an admin (upload, sync, edit, pause, remove). A document: its owner, its source's owner or an admin (verify, owner). An admin is an admin in any of the caller's teams; there is no tenant-wide role yet |

## How agents use it

agents-service with `OPS_KB_URL` asks kb-service for the tenant's knowledge bases when a thread opens (a thread may
only name knowledge bases the agent holds) and for passages on each turn, cut to the agent's grants as they are then.
Without `OPS_KB_URL` it serves no knowledge: opening a thread on knowledge answers 503 `knowledge_unavailable`, and an
agent with no knowledge bases works as before. Unit tests inject a fixture store through `create_app(knowledge=...)`
(`services/agents-service/tests/knowledge_fixture.py`); no service path falls back to it. The use-case harnesses start
a kb-service per run and fill it with the agents fixtures' knowledge through this API
(`docs/usecases/lib/seed_fixture_knowledge.py`).

## Run it

| Do | How |
|---|---|
| Serve | `make up` runs it on the shared stack; alone, `make -C services/kb-service run` |
| Migrate | `make -C services/kb-service migrate` |
| Verify | `make -C services/kb-service verify` (lint, strict pyright, tests on the test database, OpenAPI gate) |
| Seed the demo | `uv run python scripts/seed_demo_knowledge.py` in `services/kb-service` |

## Not built

| Designed in knowledge.md | State |
|---|---|
| Connectors (web crawl, SharePoint and the rest) | not started; file sources only |
| Embeddings and pgvector | not started; goes behind the `Retriever` port once models-service serves an embeddings alias |
| OCR | off: a scanned page fails with `no_text_layer` |
| Curation queue, golden sets, evaluations, metadata profiles, precedence across knowledge bases | not started |
| Answer writing in K12 | the playground answer is the top passage quoted; no model writes an answer here |
| Knowledge calls through the data gateway | agents-service calls kb-service directly with its service token |
| A files-service server | files go through the files-service library in process; the upload route moves when a server exists |
