# Every fixture of four document types is read end to end

Status: current. Id: `uc-250`. Service: `documents-service`. Layers: api. Cards: c-255, c-295, c-297.

Every text fixture of the four seeded document types (restraining notices, tax orders, supplier invoices, bank
statements) is uploaded to files-service and read by documents-service with its type. One fixture of each type is read
with Detect. For the invoice and statement master forms, five reads offer a template, a template is suggested from
them and saved as a new version, and the rest of the form (a text PDF, a shifted scan and a skewed scan) is read by
the template while files of another layout take the model path. A restraining notice scan is then read with page
images gated one setting at a time: the type version, the team's pageImages policy and the model alias. The fake model
answers what expected.json holds, so this proves the pipeline around the model, not the model's accuracy; the real-
model measurement is in `docs/services/documents-service/overview.md`.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The fake OpenAI with an answer per fixture | `services/documents-service/tests/fixtures/fake-model/script.json` (`scripts/make_fake_reads.py`), through models-service |
| files-service (scanning off) and documents-service with the four seeded types | started by the script |
| platform-service with the dev seed, for the team's pageImages policy | started by the script |
| Tesseract, for the scans | installed on the machine |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Read every text fixture with its type | Each read is done; every value matches expected.json; every field with a quote has a box |
| 2 | Read one fixture of each type with Detect | Each is read as its own type |
| 3 | List template offers for the invoice and statement, suggest a template from five master reads, save it as a new version | One offer of at least five reads per form; the version is saved |
| 4 | Read the sixth master, the shifted scan, the skewed scan and the copy with a date printed 13/45/2026 | Each is read by the template; a value OCR misreads is sent to review, and the impossible date has no value, is sent to review, and keeps what was printed as `extractedValue` |
| 5 | Read the two files of another layout | Each takes the model path with the template's miss recorded, and reads its expected values |
| 6 | Read a restraining notice scan with OCR: with page images off on the type; on the type but not the team; on for the team (a team admin is refused, the workspace's Security admin turns it on) with the alias not cleared; with an `extract` alias cleared for images; and with the team turned off again | Only the read with every setting on sends the page: its `imageCalls` names step `extract`, page 1, alias `extract`, and models-service logs that call with its image. The read against the uncleared alias is done text-only with `imageRefused` saying why |
| 7 | Correct the first invoice master's invoice number to a value its cited line does not show, then to the value it shows; list the supplier invoice type's examples, remove the new one | The first correction teaches nothing; the second is listed as an example: field `invoice_no`, the corrected value and the line it was printed on; removed, it is no longer listed |
