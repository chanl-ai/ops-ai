# A workflow turns an uploaded invoice into fields a person can check

Status: current. Id: `uc-124`. Service: `agents-service`. Layers: api. Card: c-157.

An Extract from file step asks documents-service to read a file (its bytes from files-service) into the fields a
workflow defines. Each field has a value, a confidence from the engine's own checks (the quote is on its page and says
the value; the value is valid for its type) and a citation; the run leaves by `review` when any field is below the
highest of its own threshold, the schema's and the tenant's floor, by `unreadable` when the file has no text, and by
`ok` otherwise.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The fake OpenAI with this use case's rules | `services/agents-service/tests/fixtures/invoice-extraction-fake-openai/script.json`, through models-service |
| platform-service (the floor policy), kb-service's files-service with scanning off, documents-service, and a workflow worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A text invoice PDF (two pages) through a workflow with invoice_no, amount (money) and due_date (date) | `ok`; each field has a value, a confidence and a citation {fileId, page, quote}; amount 1234.5 |
| 2 | An invoice whose answer quotes a line that is not on the page | `review`, with invoice_no in `needsReview` and confidence 0 |
| 3 | The first invoice through a workflow whose amount field must reach 0.99 | `review`, with amount in `needsReview` |
| 4 | Sam (Security admin) sets the `extractionFloor` policy to 0.95 in Govern > Policies (platform-service), then the first invoice again | `review`: amount (0.9) is below the floor though the step sets none |
| 5 | A scanned page with no text and OCR off | `unreadable` |

The worker reads the floor per step from platform-service (`services/agents-service/tests/api/test_extraction_floor.py`: an unread floor stops the step instead of using the default); who may set it is the policy route's rule (`services/platform-service/tests/test_policies.py`). Step 4 fails when the worker has no platform-service to read it from (seen failing with `OPS_PLATFORM_URL` empty).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-124-api.py` | passing |

## Non-vacuous check

Step 2 fails with grounding off: an invented quote then scores as found and the run leaves by `ok`.
