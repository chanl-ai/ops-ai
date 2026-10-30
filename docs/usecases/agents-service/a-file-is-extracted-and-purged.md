# Extract on a file saves what was read, and deleting the file purges it

Status: current. Id: `uc-244`. Service: `agents-service`. Layers: api, ui. Card: an earlier change; ui layer an earlier change.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | James asks in Files for a notice to be read as a Levy notice, and its run reads and saves it | ui | 1 | 1 |
| S2 | The file's page says it was read as a Levy notice | ui | 2 | 2 |
| S3 | Deleting the file in Files starts the purge, which ends purged | ui | 3 | 3 |
| S4 | The same through the API, with a repeated request, a correction saved again and what the purge removed | api | 1-4 | 4 |

A person asks for a file to be read with a document type (`POST /v1/files/{id}/read-requests`): files-service
reports file.read_requested, and agents-service's system extract workflow runs as that person, reads the file through
documents-service, sends fields under the floor to a person, and saves what was read on the file through files-service. Deleting the file writes a file.deleted service event in the same transaction; files-service's relay
delivers it, and the purge workflow removes what documents-service read from the file. No service calls another to
make this happen; the workflows compose them.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The fake OpenAI with the court order notice's rule | `services/agents-service/tests/fixtures/levy-extraction-fake-openai/script.json`, through models-service |
| files-service (scanning off, events to this run's agents-service), documents-service (events to this run's agents-service) with the demo's document types, agents-service and a workflow worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Upload the court order notice and ask for it to be read with `levy_notice` | 202; the request names its run once the event is delivered; the run is the person's and ends `saved` |
| 1b | Ask again with the same Idempotency-Key | The first request and its run |
| 2 | Read the file and list files with `readAs=levy_notice` | The file's `data` names `levy_notice`, `Levy notice`, the model path, a version and the extraction; the list holds only this file |
| 2b | Correct the first record's first waiting field (or its first field) | documents-service reports `extraction.corrected`; `extraction_corrected_save` saves the read on the file again: a newer `readAt`, the same extraction and type name, and `fieldsToCheck` equal to what still waits |
| 3 | Delete the file | 204; a `file_deleted_purge` run starts from the event and ends `purged` |
| 4 | Read the purge run's output | At least one extraction removed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-244-api.py` | passing |
| ui | `agents-service/scripts/test-uc-244-ui.mjs` | passing: Extract on the file's page, its Read as, and Delete in Files |
