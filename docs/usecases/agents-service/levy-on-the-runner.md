# A court order notice runs on the workflow runner from its mailbox

Status: current. Id: `uc-210`. Service: `agents-service` (the worker runs ops_engine). Layers: api. Card: c-210.

A garnishment notice in the court order mailbox starts the court order intake workflow (`levy_intake`), which reads every debtor from the PDF (Extract from
file, Several records) and starts one `levy_case` per debtor. A case finds the customer at the bank (Match: the name,
and the address or the last four of the SSN), then waits for a reviewer to Hold funds or Flag the customer. Both
workflows are v2 definitions in the dev seed (`services/agents-service/seed/engine_workflows.json`, owned by team_ops),
which this use case publishes into its own database.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Everything else | started by the script on its own ports: fake OpenAI with `tests/fixtures/levy-extraction-fake-openai`, models, files, tools with the core fake bank reaching GreenMail, agents, a worker; the script connects a court order mailbox of its own on GreenMail (IMAP) through the API and emails the notice to it |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Save and publish `levy_case` and `levy_intake` for team_ops | Both live |
| 2 | Drop the fixture notice in the court order mailbox | One intake run ending `cases_opened`; three `levy_case` runs |
| 3 | Read the cases | Marcus Bell and Priya Natarajan wait for review; Jordan Whitfield ends `not_matched` with candidate CUS-1003 |
| 4 | Maya holds 9000 on Marcus's case | The bank answers 422; the case waits on the same review (iteration 2) |
| 5 | Maya holds 1500 | The case ends `held`; the bank holds 1500 on CHQ-2219, once |
| 6 | Maya flags Priya | The case ends `flagged`; the bank has the note |
| 7 | Drop the same notice again | No second intake run, no second case |

## Non-vacuous check

Step 3's Jordan check fails when a name alone matches (`packages/ops_engine/tests/test_match_step.py`, seen failing
with the Any rules removed). Step 4 fails when a failed hold ends the case or the second decision is sent without its
approval (`test_review_loop.py`, seen failing with the approved call ignored).
