# An agent reads a team's file and a document's fields by its type, and never another team's

Status: api passing, ui failing. Id: `uc-613`. Service: `tools-service`. Layers: api, ui.

The Platform tools module of every install holds `read_file` (a team file's full text, found by id
or name) and `read_document` (a document's fields with one of the team's document types). Both are documents-service's
own reads, called through the tool gateway as the calling team, and Connections shows them as the Built in apps Files and
Document types.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent reads a team file by name and gets its text | api | 1 | 1 |
| S2 | It reads the document's fields with the team's document type | api | 2-3 | 2 |
| S3 | Another team's file is never found | api | 4 | 4 |
| S4 | In the console chat an agent reads a file by name and pulls its fields, each read shown as a tool row | ui | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| api: own services | models-service on documents-service's fake model (`services/documents-service/tests/fixtures/fake-model`), files-service with scanning off, documents-service with the seeded document types, tools-service with `OPS_FILES_URL`/`OPS_DOCUMENTS_URL` |
| ui: the demo stack | withUiStack with platform sign-in; the demo fake-OpenAI's `uc613` rules; James grants `ag_advisor` both tools and publishes it |

No real model is called: the fake answers the tax levy fixture's fields.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Upload `TAXLEVY01.pdf` as `levy-uc613.pdf` to team_ops; call `read_file` with `file: levy-uc613.pdf` as an agent run of team_ops | 200; the file's id and its text, which holds the case number SYN-TL-2026-0101 |
| 2 | Call `read_document` with the file id and the tax levy type's name | 200; `amount_due` reads $7,482.19 |
| 3 | List the call log for each tool, and Connections | A row per read; Built in shows Files and Document types |
| 4 | Upload `retail-only-uc613.pdf` to team_retail; call `read_file` with that name as team_ops | "no file named" and nothing read |
| 5 | In the console chat with `ag_advisor`, James asks "uc613 read notice-uc613.pdf and tell me the case number" (the restraining notice fixture) | The agent calls `read_file`, then `read_document` with the restraining notice type, both shown as tool rows and both succeed; the answer names SYN-2026-0006 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-613-api.py` | passing, `make usecase-test UC=uc-613 LAYER=api` (2026-11-01) |
| ui | `tools-service/scripts/test-uc-613-ui.mjs` | failing on HEAD 2026-11-01: the chat turn's knowledge search answers 404, so the agent calls no tool (same as uc-001, uc-002, uc-048) |

## Non-vacuous check

Step 4: the other team's file is found by name only if the search crosses teams; files-service's list reads the team
from the service token, and its test lists nothing for another team (`services/files-service/tests/test_api.py`). Step
1 failed while the list route refused service tokens (seen 2026-11-01), so it proves the lookup reaches files-service.
