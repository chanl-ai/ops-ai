# kb-service: working rules

Status: current.

The knowledge service (`ops_kb`, :8740) owns department knowledge bases, their sources (uploaded files, pasted
pages, and sources read through a connection's tools), sync runs, documents and their versions, chunks with page and
section, change rows, and cited retrieval. An agent granted a knowledge base cites passages from it by document,
version, page and section. A file source's files are read by documents-service (their reading, OCR on auto by
`kb_ocr`), which kb-service splits with `packages/ops_ingest`; file bytes live in files-service and kb-service holds file
ids, writing bytes itself only for items written into typed text and push sources (`POST /v1/sources/{id}/items`) and
the dev seed.

It does not own agents or their grants: "used by" asks agents-service (`agents.py`). Shared service rules:
[services/CLAUDE.md](../CLAUDE.md). Cross-folder rules: [root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_kb/app.py` | The FastAPI app and every route; models in `schemas.py`, mirroring `apps/console/src/lib/types/knowledge.ts` |
| `src/ops_kb/service.py` | Bases and sources as the console reads them, joined and counted on the server |
| `src/ops_kb/retrieval.py`, `store/fulltext.py` | The `Retriever` port and its one adapter, PostgreSQL full-text search with a score floor |
| `src/ops_kb/query_steps.py` | Rerank and question rewrite around a search, through models-service on a chat-model alias |
| `src/ops_kb/files.py` | Where a source's files are kept, through files-service |
| `src/ops_kb/readings.py` | A file's reading from documents-service and its split; `POST /v1/events` takes `reading.finished` and `reading.failed`, and the knowledge schedule asks again for items still `reading` |
| `src/ops_kb/tool_sources.py`, `schedule.py` | Knowledge read through a connection's tools, and the beat that syncs them on schedule |
| `src/ops_kb/seed.py`, `seed/` | The banker demo's two knowledge bases (markdown rendered to PDFs), seeded when a dev kb-service starts |
| `src/ops_kb/store/` | All database code; `store/knowledge.py:34` names the tenant role `ops_kb_tenant` |
| `scripts/seed_demo_knowledge.py` | Seeds the demo through the API against a running stack (`--agents` also wires the agents) |
| `migrations/` | Its own chain, version table `alembic_version_kb` |
| `tests/` | Bases and sources, sync, retrieval, ownership and write roles, team isolation, a fake files-service (`files_fake.py`) |

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8740 | `scripts/stack.sh stop kb` from the root, then `make run` (this Makefile's `stop` answers "not started") |
| Its tests | `make test`, or from the root `make test PKG=services/kb-service` |
| One test file | `PYTEST_ADDOPTS=tests/test_health.py make test`: this Makefile ignores `T=` |
| Lint, types, OpenAPI | `make lint`, `make typecheck`, `make openapi-check` (`make openapi` to regenerate) |
| Apply the chain | `make migrate` |
| Logs and health | from the root: `make logs SVC=kb FOLLOW=0`, `make health` |

## Try it as a person

```bash
make api GET /v1/knowledge-bases AS=builder SVC=kb
make api GET /v1/sources AS=builder SVC=kb
make chat-kbs AS=james                 # the knowledge bases New chat offers
```

To check a cited answer end to end, attach a base to a chat turn: `make chat AS=james SAY='…' KB=kb_…`. Reference:
[make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| Owners | A base is created with an owner; changes are its owner's or an admin's, decided by `can()` |
| One team | A base, its sources and everything under them belong to one team, held by row security; another team's id answers 404 or 409 with no team named |
| Files through files-service | A file added to a source must be the team's and scanned clean; adding it records a reference so files-service keeps it |
| No weak passages | Below the score floor nothing is returned, so an unanswerable question gets no citation |
| Versions | A known name with new content is its next version, written in the transaction that withdraws the old chunks |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/kb-service/overview.md](../../docs/services/kb-service/overview.md) | What is built: bases, sources, sync, retrieval, changes, team rules |
| [docs/packages/ops_ingest/](../../docs/packages/ops_ingest/) | Parsing and splitting |
| [docs/usecases/kb-service/](../../docs/usecases/README.md) | Use cases, including cited answers from uploaded PDFs, a website source, and typed text and pushed items |
| [openapi.json](openapi.json) | The API |
