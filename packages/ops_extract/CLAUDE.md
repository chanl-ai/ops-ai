# ops_extract: working rules

Status: current.

The checks applied to fields read from a document. A field's confidence comes from signals this package verifies (the
quote is on the page it cites, the value is a valid value of its type, OCR pages count for less), never from the model.
It also holds the file layout model, document type classification, cross-field rules, layout templates read with no
model call, and the workspace floor. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `checks` | Scoring: a field needs a person when its confidence is under the highest of its own threshold, the schema's and the workspace floor, or when it is always reviewed |
| `layout` | A file's layout: pages, blocks and table cells with ids, boxes as page fractions, reading order, words with confidence |
| `pages` | A parsed document as one text per page, the text quotes are checked against |
| `boxes` | Where on the page each field came from: one box per line and the layout block ids |
| `classify` | Which of the team's document types a file is; under the floor or unknown goes to a person |
| `rules` | Cross-field checks declared on a document type version (`sum`, `before` and the other fixed kinds) |
| `templates` | A known form read from its zones; a skewed scan misses and goes to the model |
| `floor` | The workspace's `extractionFloor` policy, read per extraction |
| `page_images` | Page and field crops a read may show the model; the caller decides whether any is sent |
| `prompt`, `result` | What the model is asked and how its answer is checked; the scored result in the shape workflows read |

## Contract with callers

- Pure functions: the caller parses the file and calls the model, then hands the answers here.
- The floor is read with the caller's own service token for the tenant. A floor that cannot be read stops the step;
  it never falls back to a default (`src/ops_extract/floor.py`).
- Document types, their rules and templates are data on a document type version; no field, category or form is
  written in code (root rule "Use cases are configuration").

Depends on `ops_contracts` (field value types), `ops_identity` and `ops_ingest`. Its only caller in code is
documents-service (`ops_documents.extraction`, `layouts`, `document_types`). The module docstrings in
`src/ops_extract/__init__.py:1` and `checks.py` name files-service's extraction API and the engine's Extract step as
callers; extraction moved to documents-service, so those docstrings are out of date.

## Run and test

| Task | Command |
|---|---|
| The suite (no database, no model) | `make test PKG=packages/ops_extract` |
| One file | `make test PKG=packages/ops_extract T=tests/test_checks.py` |
| Lint, format, types | `uv run ruff check packages/ops_extract`, `uv run ruff format --check packages/ops_extract`, `uv run pyright packages/ops_extract` |

Gap: no pool job in `make verify` runs this suite ([../CLAUDE.md](../CLAUDE.md#what-make-verify-runs-for-packages)); it
runs when the package changes.

## Reference docs

- [docs/services/documents-service/design.md](../../docs/services/documents-service/design.md) and [overview.md](../../docs/services/documents-service/overview.md)
