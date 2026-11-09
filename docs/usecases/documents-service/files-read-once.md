# A scan, a half scan and a filled form are each read once by documents-service and cited from a knowledge base by the OCR'd page

Status: current. Id: `uc-672`. Service: `documents-service`. Layers: api, sdk.

Every file is read in one place, documents-service's reading step (`services/documents-service/src/ops_documents/readings.py`
on `packages/ops_ingest/src/ops_ingest/reading/`), and kept per file content and OCR settings. A knowledge base indexes
the reading instead of parsing the file itself. The files are the reader's own test fixtures: a page that is only a
picture of printed words, a page half text and half picture, and a fillable form whose typed values are only in its
form fields (`packages/ops_ingest/tests/fixtures/`).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder uploads a scanned page and gets its words read by OCR, without the upload waiting for it | api | 1, 2 | 2 |
| S2 | A half-scanned page reads in full, the picture part included, and a filled form's typed values are read | api | 3, 4 | 4 |
| S3 | Asking for the same file again answers at once from the stored reading, and another team cannot read it | api | 5, 6 | 5 |
| S4 | A knowledge base built from the three files answers from the scanned page and says it was read by OCR | api | 7, 8 | 8 |
| S5 | A developer reads a file's reading through the Python SDK | sdk | 1 | 1 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Tesseract with English | `brew install tesseract` (the image installs `tesseract-ocr-eng`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Upload `scanned.pdf` to Files and ask documents-service for its reading (`POST /v1/documents/readings`, OCR auto) | 202, status `queued`: a scan is read in the background |
| 2 | Poll `GET /v1/documents/readings/{fileId}` | done; page 1 read by `ocr`, its text holds "LATE PAYMENT FEE", with an OCR confidence |
| 3 | Ask for `half_scan.pdf`'s reading and wait for it | page 1 read as `mixed`, with the phone, email and date that are only in the picture |
| 4 | Ask for `form.pdf`'s reading | 200 at once (no page to OCR); 8 form fields, `policy_number` = PL-90385217 |
| 5 | Ask for `scanned.pdf` again | 200 done at once, the same text: served from the stored reading, no second OCR |
| 6 | Ask for the scan's reading as another team | 404, though its bytes' reading is stored |
| 7 | Make a knowledge base with a file source holding the three files and sync it | the scans are `reading` at first, then indexed once documents-service reports `reading.finished` |
| 8 | Ask the base "What is the late payment fee?" and read the scan's item | the answer cites `scanned.pdf` page 1, and the item says page 1 was read by OCR; asking for the policy number cites the form |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `documents-service/scripts/test-uc-672-api.py` | passing |
| sdk | `documents-service/scripts/test-uc-672-sdk.py` | passing |

## Non-vacuous check

Step 5: a second ask for a scan answers 200 only when the reading is stored; with the store bypassed it answers 202
and reads the scan again. Step 2 fails with OCR off (`OPS_KB_OCR` does not apply here; the request's `ocr: "off"` lists
the page as unread instead).
