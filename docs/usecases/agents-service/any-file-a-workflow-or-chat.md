# Any file a workflow or chat reads ends read or with a reason

Status: draft. Id: `uc-620`. Service: `agents-service`. Layers: api. Card: an earlier change.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder's own workflow reads a notice with an Extract step and no save step, and Files says what it was read as | api | 1-2 | 1 |
| S2 | A notice sent through a hosted form finishes: with no mailbox it opens its cases and skips the reply; with a mailbox and no subject the acknowledgement opens with a default subject; a required field left empty is refused by the API as the console refuses it | api | 3-5 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The fake OpenAI with the levy notice's rule | `services/agents-service/tests/fixtures/levy-extraction-fake-openai/script.json`, through models-service |
| files-service and documents-service delivering events to this run's agents-service, and a workflow worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a workflow with Extract from file as `levy_notice` and no Save data on file step; start it with the notice | The run succeeds; the file's `data` names `levy_notice`, `Levy notice`, the fields to check and the extraction |
| 2 | List `extraction_read_save` runs | One ended `saved`: documents-service reported `extraction.read` |
| 3 | Share a team copy of `mail_document` as a form; submit the notice with a sender and no mailbox | The run ends `cases_opened` with a message naming no mailbox, sender or subject |
| 4 | Submit again with a mailbox and no subject | The run waits at the acknowledgement, whose reply has the subject "We received your document" |
| 5 | Submit with the file and sender empty; start by hand through the API with the sender empty | 422 `invalid_input` naming the empty required fields |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-620-api.py` | passing: S1, S2 (5 of 5) |

## Non-vacuous check

On 8195ab8a plus the service changes but the old seeds, steps 1-4 failed: no data on the file, no
`extraction_read_save` run, the form refused an empty mailbox, and the acknowledgement failed with "Reply from the
mailbox has no subject to use from this run."
