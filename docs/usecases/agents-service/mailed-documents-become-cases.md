# Documents emailed to a team mailbox become cases, and the sender gets a reply

Status: current. Id: `uc-223`. Service: `agents-service` (the worker), `tools-service` (IMAP, the reply), `files-service`. Layers: api. Card: c-223.

A notice PDF and a CSV of debtors emailed to a team's IMAP mailbox each become a child run (`mail_document`) that
reads every debtor (Extract from file, Several records) and opens a levy case per debtor. Attachments files-service
refuses under the tenant's limit (Settings > Storage) are listed on the run as `skipped`, and the mailbox keeps
reading. A read below the floor waits for a person before any case opens. A reviewer's approval sends one
acknowledgement from the mailbox's own sender.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA, GreenMail and Mailpit | `make db-up` |
| Everything else | started by the script on its own ports: fake OpenAI with `tests/fixtures/mail-intake-fake-openai`, models, kb and its files-service, tools with the core fake bank, agents, a worker |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Limit case attachments to PDF and CSV up to 1 MB; connect a fresh IMAP mailbox on GreenMail with an SMTP sender (Mailpit); publish levy_case, mail_document, mail_intake | All saved |
| 2 | Mail a notice PDF, a debtors CSV, a 2 MB PDF and a .exe | The intake run stores the PDF and CSV by id; `skipped` lists the 2 MB file (`too_large`) and the .exe (`type_not_allowed`) |
| 3 | Wait | Two document runs, each waiting on its acknowledgement; four levy cases: Marcus, Priya (twice, once per file) waiting for Hold or Flag, Jordan ended not matched |
| 4 | Maya approves the PDF's acknowledgement | One reply in Mailpit from the mailbox's address to the sender; the document run ends `replied` |
| 5 | Mail a notice the model misreads | Its document run waits on Check the read; rejected, it ends `needs_manual_read` and no case opens |
| 6 | Send the first message again (same Message-ID) | No new intake run, no new case |

## Non-vacuous check

Step 2 fails when a refused attachment fails the pass (`tests/engine/test_email_trigger.py::test_an_attachment_files_service_refuses_is_skipped_and_the_mailbox_keeps_reading`, seen failing with refusals re-raised): the message is read again forever and later mail never starts a run. Step 5 fails when a field's quote is not checked against its page (`packages/ops_engine/tests/test_extract_step.py`).
