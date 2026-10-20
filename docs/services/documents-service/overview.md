# Documents service

Status: first slice built (c-256). documents-service runs on :8760 (`make up` starts it as `documents`) with its own
tables and migration chain (`alembic_version_documents`). It serves the extraction API (c-235) and document types,
their versions, samples and capped test runs (c-236), the layout (c-247), classify (c-249), and boxes on every
extracted field (c-252). Templates (c-253, c-254) are planned. Design: `.codeloop/wiki/concepts/documents-subsystem.md`.

| Item | Detail |
|---|---|
| Purpose | What is read from a file: extractions with each field's value, confidence, page and quote, and the document types that say which fields a kind of document carries. |
| Owns | `extractions`, `extraction_corrections`, `document_types`, `document_type_versions`, `document_type_samples`, `document_type_tests`, `documents_layouts`, `documents_outbox` (chain `alembic_version_documents`). Never file bytes. |
| Depends on | files-service for bytes (`ops_files_client`, as the caller's team), models-service for model calls (its own key `mk_dev_extract`, purpose `files:extract`, a budget share per tenant), platform-service for the `extractionFloor` policy. |
| Libraries | `packages/ops_extract` (the checks that score a field, the floor, the prompt), `packages/ops_ingest` (parsing and OCR). |
| Client | `packages/ops_documents_client`: `extract` (answer or poll to the end) and `document_type`. |

The service map that applies to every service is `docs/architecture/service-map.md`.

## Rules

| Rule | Why |
|---|---|
| Bytes are read through files-service as the caller's team; a file that team cannot see is 404, and a file not scanned clean is refused | Files keeps bytes and decides who sees them; a second store of bytes would need its own retention and holds |
| A field below the threshold (the step's `reviewBelow` or the workspace floor, whichever is higher) is marked in `needsReview`; documents-service opens no task | A workflow decides what happens to a marked field. Subsystems compose through workflows, not through each other |
| `POST /v1/documents/purge` is for services only (`documents:delete`) and removes a file's extractions and samples | Called by a system workflow on the file-deleted trigger (workflows lane). files-service calls nobody when it deletes |
| A document type version never changes once saved; a workflow save pins the newest version | A running workflow reads the fields it was tested with |
| A test run reads at most 20 samples, and its estimate is shown before it starts | Each sample is one model call |
| The workflow runner and the agent kernel never import `ops_extract` | The checks run in one place; `scripts/tests/test_no_cross_service_imports.py` enforces it |

## Routes

| Route | Scope for a service | What it does |
|---|---|---|
| `POST /v1/documents/layout` | `documents:run` | `{fileId, ocr?}`: the file's layout, read on the first ask and cached by tenant, content digest, layout engine version and OCR choice: pages, blocks in reading order with table cells, words with confidence, boxes as page fractions (c-247) |
| `GET /v1/documents/layout/{fileId}?page=&ocr=` | `documents:view` | The cached layout or one page of it; 404 until it is read |
| `GET /v1/documents/extractions?fileId=` | `documents:view` | A file's extractions by the caller's team, newest first, paged (c-250) |
| `POST /v1/documents/extractions` | `documents:run` | `{fileId, fields or documentTypeId, version?, many, ocr, reviewBelow}`. A small file answers 200 when done; a larger one 202, to poll. `Idempotency-Key` returns the same extraction |
| `GET /v1/documents/extractions/{id}` | `documents:view` | The extraction, with fields, `needsReview`, floor and corrections |
| `PATCH /v1/documents/extractions/{id}/fields/{key}` | `documents:edit` | A correction; the original value and confidence are kept |
| `POST /v1/documents/purge` | `documents:delete`, services only | `{fileId}`: removes what the token's team read from a deleted file; 409 while files-service still serves the file, so a live file's reads are never removed |
| `GET, POST /v1/document-types`; `GET /v1/document-types/{id}` | `documents:view`, `documents:edit` to create | The team's types, with `canCreate` and `canEdit` from the caller's `documents.edit` |
| `POST /v1/document-types/{id}/versions`, `.../samples`, `DELETE .../samples/{sampleId}` | `documents:edit` | Version n+1; a sample holds a `test_set` reference on its file |
| `GET .../versions/{n}/test-estimate`, `POST .../versions/{n}/test-runs`, `GET .../test-runs/{id}` | `documents:view`, `documents:run` | Estimate, start and read a test run |

People are checked against the `documents` permission area: view to read, run to extract, edit to create or change a
type or correct a field; delete is for services. Built-in roles: admin
holds every action; builder, reviewer and viewer hold view, edit and run (platform migration 0023).

The console's Data Hub > Document types (`/document-types`, c-243) lists the team's types and opens one on a version
picker with Fields, Samples and Tests tabs; its write controls follow `canCreate` and `canEdit`, so with every member
holding `documents.edit` no one sees it read-only until RBAC lands. Proof: uc-243
(`docs/usecases/documents-service/builders-manage-document-types.md`); page row in `docs/console/page-plan.md`.

## Workflows that use it

Subsystems compose through workflows (c-250); no service calls another to make something happen.

| Workflow | Started by | Steps |
|---|---|---|
| `system_extract` | files-service's `file.read_requested`, when a person asks `POST /v1/files/{id}/read-requests {documentTypeId, version?, typeName?}`; the run is that person's | Read the file (Extract from file), a person checks fields under the floor, Save data on file (`PUT /v1/files/{id}/data`) |
| `file_deleted_purge` | files-service's `file.deleted`, written in the transaction that deletes the file | Purge (`POST /v1/documents/purge`) |
| `extraction_corrected_save` | documents-service's `extraction.corrected`, written with a person's correction of the file's newest read | Save data on file with the corrected read; a corrected field no longer counts as waiting |

A workflow records what a file was read as with its Save data on file step (`PUT /v1/files/{id}/data`), never the
Extract from file step itself (c-378). The step takes the type's name from the read's `documentType`, which
documents-service names, so a workflow need not pass one. Each seeded workflow that reads a file of a document type
(`mail_document`, `levy_intake`, `levy_read_one`, `system_extract`, `attachment_record`) saves the read on its ok and
review paths; without one Files says "Not read" while the Fields tab shows the read. A read with fields of its own
names no type and is not saved.

files-service writes both events to its outbox (`files_outbox`) and a relay delivers them to agents-service's
`POST /v1/events`; a read request (`file_read_requests`) records the run it started, which
`GET /v1/files/{id}/read-requests/{key}` returns. A repeated Idempotency-Key returns the first request.
documents-service writes `extraction.corrected` to its own outbox (`documents_outbox`) and relays it the same way; it
never writes to files-service itself. The event waits 5 seconds before it is due, and a newer correction of the same
extraction marks the waiting one superseded (never sent, never marked sent), so several corrections in a row start one
Save data run with the final read. Delivered and superseded rows are pruned after 7 days.

## What an extraction reads

Extraction reads the file's cached layout, not a second parse (c-247). Page text lists blocks in reading order with
titles and headings on lines of their own; a two-cell table row (a label and its value) becomes two lines, and a wider
row (a spreadsheet or CSV record) stays one line joined by ` | `. Words far apart on one line (a two-column caption)
are separate lines. An OCR'd field scores at the mean recognition confidence of its quote's words instead of a flat
0.7.

Each field whose quote is found on its page carries `boxes`, one `{page, x, y, w, h}` per printed line as fractions
of the page from the top left, narrowed to the value's words when the quote includes a label, and `blocks`, the layout
block or table cell ids they sit in (c-252, `ops_extract.boxes`). A quote not on its page, a file without word boxes
(DOCX, HTML, text) and reads made before c-252 carry none. On a page OCR turned upright or straightened (c-294), each
word's box is mapped back through those turns, so it lies where the word is printed on the scan as uploaded
(layout-3). On five real levy reads every quoted field was boxed.

A document type version may hold layout templates (c-253): per template page, anchor labels with the box each is
printed in and one zone per field, boxes as page fractions. Before the model, each template is matched against the
file's layout: a page matches when every required anchor is found within 0.03 of its box and 80% of its anchors are
found; the anchors' mean offset moves the zones, and each zone's words are scored by the same field checks as a model
answer. A match answers `path: "template"` and `templateId` with no model call and no measured tokens (so the test
estimate keeps pricing model reads). No match, or a required zone that reads nothing valid, takes the model path with
`templateMiss` (`templateId`, `score`, `missingAnchors`). Types reading several records always take the model path;
rotation and scale are not corrected. Test-run rows carry each sample's `path` and `templateId`. A new version that
does not name `templates` carries the latest version's forward; one reading a field the new version lacks is kept with
`needsRebuild: true` and never matched. Naming `templates` (even `[]`) replaces them. The seed is create-only: a type
that exists is left as people left it.

A builder gets a template without drawing it (c-254). `POST /v1/document-types/{id}/templates/suggest
{extractionIds}` drafts one from the team's finished reads of the type: each field's zone covers its boxes, widened
for a longer value, and its anchor is the nearest label words to the left on the same line or on the line above, never
a value's words; across several reads an anchor is kept only where every file prints it in the same place. The answer
shows how the draft reads each of those files. Nothing is saved: the builder posts the draft as a new version.
`GET /v1/document-types/{id}/template-offers` lists groups of at least the version's `offerAt` (5 unless set, at least
2, carried forward like templates) checked model reads (nothing left to check)
that share a layout fingerprint (the words that are not values, positions rounded) and that no template of the latest
version reads. A model read stores its fingerprint when it finishes, so a listing groups stored values and reads one
layout per offered group; a read saved before that gets its fingerprint on the first listing that sees it.

A document type version sets `dateOrder`, how a numeric date reads: `MDY` (03/04/2026 is March 4, the default, for US
documents) or `DMY`.

A version may carry checks across its fields (c-296), from two kinds: `sum` (`fields` must add up to `equals`
within `tolerance`, 0.01 by default) and `before` (the `earlier` date must not come after the `later`). A check runs
only when every field it names has a value. After scoring, every field a rule rejected (its type, now named
`rejected: "type"`, its pattern, emptyWhen, or a check) is asked again in one model call naming only those fields and
why each failed; a re-read value that passes every rule replaces the first (`reread: true`), and one that fails again
goes to review with `rejected` naming the rule (`check:<id>` for a check) and the first value kept as
`extractedValue`. A template read does the same and stays on the template path; a required zone that reads nothing
still sends the file to the model. A new version that does not name `checks` carries the latest forward, dropping one
naming a field it lacks.

A version may let reads show the model the page image (c-295, `pageImages`, off by default). The image carries
everything printed on the page to the model provider, so three settings must all allow it: the version (turning it on
needs `documents.manage`, held by team admins; a later version carries it forward), the team's `pageImages` policy
(per team, read live from platform-service, off for a team that set nothing, changed under `settings.manage` in the
Security team; an unreadable policy counts as off), and the model alias version's `images` clearance in models-service,
which refuses an image to an alias not cleared (403 `images_not_cleared`, logged denied). A page read through OCR goes
whole with the first read (at most 4 pages, drawn at 150 dpi, longest side 1600 px). On any page, a field that fails a
rule or reads below its review threshold goes to the one re-read with a crop around its boxes, margin wide enough to
take in its label; a doubtful field with no boxes adds no crop, and a text page whose fields all pass sends nothing.
Every call that carried an image is listed on the read as `imageCalls` (`step`, `pages`, `images`, `alias`) and counted
in models-service's call log (`images`). An alias not cleared makes the read go on text-only with `imageRefused` saying
why. Image tokens are not in the test estimate. A value read only from the image has no quote, so it gets no box.

Corrections teach the type (c-297). A person's correction of a read of a document type keeps an example: the field,
the line its value was printed on (the read's quote for it) and the corrected value, for that tenant, team and type
(`document_type_examples`, documents_0010), only when that line shows the corrected value (`ops_extract.checks.in_quote`):
a wrong read often cites the wrong line, and pairing it with the right value teaches every later read a false one. A
later correction of the same field on the same read replaces it, and the
same field, line and value from another read adds nothing. A model read of the type is given the 3 newest examples
of each field it asks, 12 at most, as corrections on earlier documents of the kind; a template read calls no model,
and its re-read of a failed field is given them too. `GET /v1/document-types/{id}/examples` lists them newest first
for the team (documents.view), the printed line and the corrected value masked as the team's `aiStepsMaskPersonalData`
policy masks personal data (masked when the policy cannot be read); the stored example the model is given stays real.
`DELETE /v1/document-types/{id}/examples/{exampleId}` (documents.edit) removes one. A field keeps its newest 10
examples (`EXAMPLES_KEPT_PER_FIELD`), and a purge of a deleted file removes the examples its reads taught.

A field may be marked `keyField: true` (c-303): a review shows key fields first and requires them checked. The mark
is a boolean, refused otherwise when the version is saved, and every read's `schema` carries it.

A field may carry two rules, checked before scoring: `pattern`, a regular expression the whole value must match, and
`emptyWhen`, phrases that mean the document gives no value. A value that breaks one is emptied, kept as
`extractedValue`, marked `rejected` and sent to review. Before them, `clean` lists cleanup rules run on the model's
text (c-287): `trimPunctuation` (a trailing comma after a name), `lastFour` (the last four digits of a masked number),
`stripLabel` (a leading "Case reference: "). What the model said stays as `extractedValue`, and `cleaned` names the
rules that changed it. On the levy fixtures' stored reads at default effort they take 59/65 values right to 63/65. The test estimate prices each call at the type's last 20
measured extractions, then the tenant's, then a fixed guess (`basis`).

## Run the checks

```bash
make -C services/documents-service verify
```

Tests need PostgreSQL (`make db-up`); files-service is faked at its routes (`ops_files_client.testing`) and the model
at the Models port.

## Sample documents as requirements

The restraining-notice samples (transcribed from photographs of synthetic test documents, which stay out of this repo)
are fixtures in `services/documents-service/tests/fixtures/restraining/` (c-248). Each row is a requirement on the
reader and one check in the proof use case (c-255).

| File | What it is |
|---|---|
| `notices.json` | The source: each notice's layout, the edge it tests, what is invented, and every field's expected value as printed (null: must come back empty) |
| `TEST001.pdf` to `TEST012.pdf` | Text PDFs of the photographed notices; TEST010 is image-only and degraded, as photographed |
| `TEST001_scan.pdf`, `TEST003_scan.pdf` | Scanned copies: grey paper, skew, speckle, 120 dpi, no text layer |
| `VAR01.pdf` to `VAR07.pdf` | Invented layout variants with an amount, a date served and a response deadline |
| `expected.json` | What each file should read, generated from `notices.json`; the tests and the seed read it |

`uv run python scripts/make_restraining_fixtures.py` (in `services/documents-service`) rebuilds every file;
`tests/test_restraining_fixtures.py` fails when `expected.json` and `notices.json` disagree.

Invented, so not in any photo: TEST003's page 2 (the defendant's full SSN and a second party's number), the case
numbers cut off in the TEST001, TEST004 and TEST011 photos, and every variant. The photos stay out of ops-ai.

| Sample | Requirement | Check (c-255) |
|---|---|---|
| TEST001 | The garnishee address comes from the "TO" block when another bank address appears on the page | `garnishee_address` equals the TO block |
| TEST003 (page 2 invented) | A record spanning pages stays one record: the masked SSN on page 1 and the full SSN on page 2 belong to one debtor | Both values in one record, each citing its own page |
| TEST004 or TEST005 | A masked SSN stays masked; nothing fills in digits | `ssn_last4` read, `ssn_full` null |
| TEST006 | Four address blocks compete; each address field cites its own block | Sender, debtor, attorney and recipient addresses each from their block |
| TEST007 | Absent fields are null and marked for review, never invented | Missing fields null and in `needsReview` |
| TEST008 | Two identifiers for one debtor are both kept | Federal EIN and state tax id in separate fields |
| TEST009 | One PDF with two writs is one row holding two case groups, each value kept with its own case | Two groups; Case A's EIN with Cedar Sample LLC, Case B's SSN with Reese Example |
| TEST010 | An image-only, degraded page is read through OCR, with lower confidence sent to review | Fields read; low-confidence fields in `needsReview` |
| TEST011 | An invalid-looking SSN (000-00-0000) is kept as printed and flagged | Value kept, field in `needsReview` |
| TEST012 | The document type carries provenance rules: the attorney comes from the signature block, not the letterhead | Attorney equals the signature block |
| Layout variants (invented) | VAR01 to VAR05 share one layout; VAR06 has a two-column caption and VAR07 continues onto page 2, so templates get a match, an unknown and a suggested case | Template outcome per file: matches, unknown, suggested |
| Amounts and dates (invented) | The variants carry an amount, a date served and a response deadline, which the photos lack | Amount normalised; both dates read as dates |

A `restraining_notice` document type (19 fields) is seeded with the 16 text PDFs as its samples
(`scripts/seed_document_types.py`); each field's description carries its provenance rule, such as "counsel from the
attorney signature block only". TEST009's two case groups are not samples of it: a flat type holds one debtor, and
the groups wait for tables (c-238).

## Baseline accuracy (model path)

restraining_notice v1 tested on its 16 text samples on the shared stack, 2026-10-18, alias `extract` on gpt-5-mini,
no templates, after c-260 (headings in page text). 180 expected values in all.

| Measure | Value |
|---|---|
| Field accuracy as scored | 145/180, 80.6% |
| With a leading "Label \| " stripped from the value | 169/180, 93.9% |
| Model calls, cost | 16 calls, $0.0792 (the estimate said $0.0352: about 2,300 output tokens a call against the 600 it assumes) |
| Time | 7 min 23 s for the run, 27.6 s a call on average, 33.2 s the slowest |

| Edge | Result |
|---|---|
| TEST003 full SSN on page 2 | Read, last four match |
| TEST012 attorney from the signature block | Read, not the letterhead sender |
| TEST011 invalid-looking SSN | Kept as printed |
| TEST004 masked SSN stays masked | Missed: `ssn_full` filled with "\*\*\*-\*\*-4321" |
| TEST007 address not supplied | Missed: "Not supplied on this form" returned as the address |
| VAR06 two-column caption | Missed: "QUINN CAPTION, Defendant." as the name, "RESTRAINING NOTICE -against-" as the kind |
| VAR01 to VAR05, VAR07 | Every field read |

Most misses (24 of 35) are one pattern: on a table notice the model returns the table row ("Taxpayer \| Morgan
Example") instead of the value, because page text renders a table row as `label | value`.

## Accuracy, time and cost per path

Measured on the shared stack on 2026-10-19 with `experiments/measure_paths.py`: alias `extract` on gpt-5-mini at
default effort, the restraining notice v4 and tax levy v3 (with cleanup rules) and the two non-levy types. Accuracy
counts each expected value compared as a test run compares it.

| Path | Reads | Fields right | Time a file | Cost a file |
|---|---|---|---|---|
| Model, fresh reads (5 levy, 5 non-levy, one an OCR'd skewed scan) | 10 | 80/84 (95%) | 20.0 s mean, 10.7 to 32.5 s | $0.0044 mean, $0.0022 to $0.0062 |
| Model, stored reads (5 levy, read before the cleanup rules) | 5 | 59/65 (91%) | from the stored calls, about 25 s | from the stored calls, about $0.0055 |
| Template, suggested from one model read of each non-levy master form | 14 | 90/91 (99%) | 0.02 s on a text PDF or a cached scan layout; 0.42 s the first time a scan is OCR'd | none |

Page images (c-295), `experiments/measure_page_images.py`, 2026-10-19: two OCR'd levy scans read 24/25 text-only and
25/25 with the page image (the restraining notice's `notice_kind` was the miss), one image each, $0.0056 and $0.0043 a
read against $0.0044 and $0.0042 text-only. The invoice scan read by its template with a review threshold of 0.99 sent 7
crops on its re-read and read 7/7 for $0.0024. 5 calls, $0.021 in all; `pageImages` was turned off again after.

Corrections teaching the type (c-297), `experiments/measure_type_examples.py`, 2026-10-19, stopped after 5 of 10 calls
when the shared stack went down: the restraining notice scan read `notice_kind` as the synthetic-document banner, and
its correction taught that banner line as where "Notice of tax levy" is printed; another restraining notice read after
it fell from 11/11 to 9/11, `notice_kind` read as a tax levy. That finding is why a correction now teaches only when
its cited line shows the corrected value; that correction would teach nothing. **Unverified:** no rerun since the fix,
so the gain from examples is not yet measured.

After c-294 (scans turned upright and straightened from 1.75 degrees before OCR, layout-2) the four invoice and
statement scans, shifted and skewed, read 26/26 on the template path, about 0.9 s each for a first OCR, with no model
call (2026-10-19, read again on the shared stack); the skewed invoice's due date was the template's one miss before.

The four fresh model misses: three values on the skewed invoice scan, where OCR misread digits, and TEST009's title.
The template's one miss is that scan's due date read as 41/18/2026, which fails as a date and goes to review. The
levy fixtures are each a different layout by design, so none of them is read by a template; restraining notices and
levies printed from one master would be. An eleventh model call happened in the first run: a skewed statement scan
missed a template suggested before the zone cap and the model read it (6/6, 12.8 s, $0.0028), which is the intended
fallback; after the fix the template reads that scan.

## Gotchas

- files_0006 drops the moved tables and documents_0001 creates them again, so the documents chain runs after files
  (`make migrate`, `scripts/schema_sync.py`, both harnesses).
- A service token claiming a scope outside its caps in `Settings.service_scopes` is refused with 401, not 403.
