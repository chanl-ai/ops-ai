# A file is read with Detect from the Files page

Status: passing. Id: `uc-331`. Service: `files-service`. Layers: api, ui. Card: an earlier change.

A person asks the Files page to read a file without choosing its document type. files-service accepts the read request
with no type, and the system extract workflow reads the file with Detect: documents-service classifies it over the
team's types and reads it with the one found, and the file records that type. A file of none of the team's types goes
to a person's check and, once approved, is saved with no type (not recognised). A request naming a type reads with it
as before. The fake model answers what the fixtures expect, so this proves the chain, not the model's accuracy.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The fake OpenAI with the documents fixtures' answers and a "no type fits" answer for a canteen menu | `services/documents-service/tests/fixtures/fake-model/script.json` (`scripts/make_fake_reads.py`), through models-service |
| files-service (scanning off) delivering its events to agents-service, documents-service with the seeded types | started by the script |
| agents-service with its shipped `system_extract` workflow, and a workflow worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Upload an invoice fixture and post a read request with no body | 202 with `documentTypeId` null; the run reads with Detect and ends saved; the file records type `supplier_invoice`, named "Supplier invoice", with its extraction |
| 2 | Upload a canteen menu and post a read request with no body; approve the run's check as Maya Okafor | The run waits for the check; once approved it ends saved, and the file records its extraction with no type, no version and no type name |
| 3 | Upload another invoice and post a read request naming `supplier_invoice` | The run reads with that type and the file records it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `files-service/scripts/test-uc-331-api.py` | passing |
| ui | `files-service/scripts/test-uc-331-ui.mjs` | passing: the Extract dialog's Detect choice (first, not chosen for you, no version) reads an invoice as Supplier invoice, and a canteen menu, once its check is approved, as Not recognised |

## Non-vacuous check

Check 1 fails when the engine reads a `documentType` whose id resolved to nothing as a type: the workflow then sends
`documentTypeId: null` and the read fails instead of detecting.
