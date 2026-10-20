# A mailbox workflow takes every shape of email

Status: passing. Id: `uc-226`. Service: `agents-service`. Layers: api. Card: c-259.

One workflow handles the shapes a team mailbox receives. A Switch reads what came in and picks one way: an
attachment with text, several attachments, text only, or nothing readable. Text only is read from the text file the
Email received trigger stores in Files (`bodyFile`). Several attachments start one Read one document run each. An
attachment with text is read twice and Combine facts compares the two; when they disagree the run stops at the read
check with both values. The script starts the workflow through the run API with the input the trigger hands on; the
trigger storing the text is `services/agents-service/tests/engine/test_email_trigger.py`.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The demo stack on the run's own ports, with a worker | the script's `withUiStack({ platform, demo })` and `startWorker` |
| The fake model's reads of the five documents | `services/models-service/seed/demo-fake-openai/script.json`, the `UC226` rules |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James publishes Read one document and Every shape of email | Both live |
| 2 | An email with only text | The Switch takes `text_only`; the text file is read; case NS-2026-GN-01187 |
| 3 | An email with two attachments | `attachments`; two Read one document runs, Marcus Bell and Priya Natarajan |
| 4 | An attachment and a text that name different case numbers | `one_and_text`; the run waits at the read check; conflicts lists case_no with both sources |
| 5 | An email with nothing to read | `otherwise`; outcome unreadable |

The non-vacuous check is step 4: if Combine picked the attachment's case number silently, the run would end
`combined` instead of waiting at the read check, and the check fails.

## Run

`ISOLATED=1 make usecase-test UC=uc-226 LAYER=api`. Every extraction is the fake model; no real model call.
