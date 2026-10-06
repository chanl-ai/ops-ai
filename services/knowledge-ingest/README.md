# Knowledge ingestion

Status: library in progress. Parsing, splitting, metadata mapping and holds, dedupe and versions, and
source rules exist as a Python library with tests. There is no server, sync workflow, storage,
embedding or AI gateway client yet.

| Item | Detail |
|---|---|
| Purpose | Syncs knowledge sources, enforces required metadata, chunks, embeds through the AI gateway under the ingestion identity, indexes, tracks freshness and maintains the citation index that triggers re-tests. |
| Owns | Separate PostgreSQL instance with pgvector; source copies in the object store. |
| Depends on | Source systems (through the data gateway's network zone), the AI gateway, `services/shared`. |
| Specs | `docs/specs/02-knowledge.md` 4, 5.1–5.8, 5.14, 5.15, 5.18; ADR-0006, ADR-0008 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.

## Run the checks

Needs Python 3.12 and uv. OCR tests also need the `tesseract` binary on `PATH` (`brew install tesseract`
or the distribution's `tesseract-ocr` package); without it they are skipped.

```bash
cd services/knowledge-ingest
uv sync --extra ocr
uv run ruff check
uv run pyright
uv run pytest
```

The failure modes the tests guard are listed in `tests/README.md`.

## What exists

| Module | What it does | Spec |
|---|---|---|
| `knowledge_ingest.parsers` | `parse(bytes, filename=…)` for PDF, DOCX, XLSX, CSV, HTML, TXT and Markdown into one `ParsedDocument`: sections with heading paths, paragraphs, tables with header rows, page numbers, source metadata. PDF tables are read with their headers and removed from the page text; headings come from font size; a page with no text layer is OCR'd with `parsing.ocr`, else reported in `pages_without_text`. HTML with `clean` drops navigation, banners, sidebars and footers. Files over 50 MB fail with `too_large` | 1.9, 5.7, 5.14 |
| `knowledge_ingest.split` | `Pipeline` and `split(document, settings)`: the one split used by sync and preview. Validates settings (`invalid_ingest`), composes strategies, returns chunks, index units, counts and notes shaped like the console's `SplitPreview` | 5.14, 5.18 |
| `knowledge_ingest.strategies` | `structure`, `fixed`, `table_rows` (column roles, key column, numeric bands), `context_headers`, `parent_child`, `clean`, and the AI steps `topic` and `faq` behind the `ModelClient` protocol. `summarize` is present but not selectable, because the console's `IngestStrategy` has no such value | 5.14 |
| `knowledge_ingest.metadata` | Mapping from `static:`, `field:` and `ai:` sources; department from the collection; sensitivity never lowered; required-metadata holds per knowledge base; no chunks for a knowledge base that holds the item | 1.1–1.3, 4.3, 15.7–15.9 |
| `knowledge_ingest.dedupe` | Content digest (SHA-256 of normalised text after `clean`), duplicates keyed by digest, collection, sensitivity and permission scope; effective-dated version chains with `current`, `superseded` and `scheduled` | 1.4–1.6, 15.3–15.6 |
| `knowledge_ingest.rules` | Include and exclude rules on path glob, title, MIME type, modified after and size under; exclude wins; the decision names the rule in words | 15.1 |
| `knowledge_ingest.model_client` | `ModelClient.complete(prompt, *, alias, max_tokens) -> str`. Strategies call models only through it (ADR-0008). The only implementation here is `knowledge_ingest.testing.FakeModelClient` | 14.9, 14.12–14.14 |

Settings models mirror `apps/console/src/lib/types/knowledge-ingest.ts` and `knowledge.ts` (`Rule`,
`MetadataMapping`, `ParsingSettings`) in snake_case and accept the console's camelCase JSON unchanged.

## Not built yet

| Gap | Note |
|---|---|
| AI gateway client | Needs `services/ai-gateway`; until then AI steps run only against the fake |
| Token counts from the embedding alias's tokenizer (spec 14.3) | Counts are approximate (about four characters per token); the pipeline accepts a counter so the real one can be passed in |
| PPTX parsing (spec 1.9) | Not ported; the earlier implementation had no PPTX parser |
| Vision descriptions of figures (`parsing.vision`) | Later phase in the spec |
| `ai:` metadata extraction (spec 14.15) | Mappings are recognised and listed in `pending_ai`; no extraction step yet |
| Tables that continue across PDF pages | Each page's part is read as a separate table |
| Sync workflow, storage, embedding, indexing, freshness | The service around this library |

## Third-party code

The parsers and strategies were ported and rewritten from an earlier chanl-ai internal implementation
(a document-processing service and a set of chunkers). chanl-ai holds the rights to that code, and the
ported code is released here under Apache-2.0. Its tests were HTTP integration tests against a running
service and a hosted database, so none were carried over; the tests here are new.

Changes from the earlier implementation that matter to behaviour:

| Earlier behaviour | Now |
|---|---|
| PyMuPDF for PDF text | pdfplumber only. PyMuPDF is AGPL-3.0, which would require releasing the service's source to anyone using it over a network, or a commercial licence; pdfplumber covers text, tables and page rendering for OCR under MIT |
| Tables flattened into pipe-separated text | Tables kept with header rows, so `table_rows` can address columns |
| Sentence packing let one long sentence exceed the chunk size | Long sentences are cut at word boundaries (test S1) |
| HTML boilerplate matched by substring, so `class="lead"` matched `ad` | Whole-token matching (test P10) |
| AI chunkers created a provider client from an API key | `ModelClient` protocol; the AI gateway holds keys |
| pandas for spreadsheets, trafilatura for HTML | openpyxl and the `csv` module; BeautifulSoup with explicit rules |

Runtime dependencies:

| Package | Licence | Used for |
|---|---|---|
| pydantic, pydantic-core, annotated-types, typing-inspection | MIT | Models |
| typing-extensions | PSF-2.0 | Models |
| pdfplumber | MIT | PDF text, tables, page rendering |
| pdfminer.six | MIT | PDF text layer (through pdfplumber) |
| pypdfium2 (bundles PDFium) | Apache-2.0 or BSD-3-Clause; PDFium BSD-3-Clause | Page rendering for OCR (through pdfplumber) |
| Pillow | MIT-CMU | Page images (through pdfplumber) |
| charset-normalizer | MIT | Through pdfminer.six |
| cryptography, cffi, pycparser | Apache-2.0 or BSD-3-Clause; MIT-0; BSD-3-Clause | Encrypted PDFs (through pdfminer.six) |
| python-docx, lxml | MIT; BSD-3-Clause | DOCX |
| openpyxl, et-xmlfile | MIT | XLSX |
| beautifulsoup4, soupsieve | MIT | HTML |
| pytesseract (extra `ocr`) | Apache-2.0 | OCR |
| Tesseract OCR (system binary, extra `ocr`) | Apache-2.0 | OCR |

Development only: pytest (MIT), ruff (MIT), pyright (MIT), reportlab (BSD, builds the PDF fixture),
types-openpyxl (Apache-2.0).
