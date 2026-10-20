# A team's mailbox runs end to end

Status: passing (2026-10-19). Id: `uc-245`. Service: `agents-service`. Layers: ui. Card c-230, epic c-227.

A team connects its mailbox in the console, binds the levy workflows to it through publish review, and from then on
every email is run once, read, checked by a person when the read is doubtful, turned into a case, and answered from
the team's own address. This is the mailbox path with nothing faked but the bank and the model: real SMTP into
GreenMail, IMAP reads through tools-service with the password on the Secrets page, the egress allow-list, and the
reply read back from Mailpit.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA, GreenMail and Mailpit for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-245 LAYER=ui ISOLATED=1` |

The stack is the banker demo (`withUiStack({ demo: true, tools: { mail: true } })`): platform sign-in, models on the
fake OpenAI with the demo's rules, tools-service with the core fake bank, and `mail.northfield.test` /
`smtp.northfield.test` resolving to GreenMail's IMAP and Mailpit's SMTP. Publish reviews stay pending
(`OPS_REGISTRY_AUTO_APPROVE=false`), so a second person approves every publish.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Sam (Security) puts the mailbox password on the Secrets page for team_ops and allows both mail hosts and their range | 201 for the secret and each allow-list entry |
| 1 | James connects the mailbox on Channels > Email: Other IMAP, plain IMAP to GreenMail, SMTP replies through Mailpit, both secrets picked; Test connection | Every test step passes; the record's sender is SMTP from the mailbox's own address |
| 2 | James publishes copies of levy_case, mail_document and mail_intake bound to the mailbox | Each publish request is pending; James approving his own is 403; Priya approves all three |
| 3 | A court clerk emails a notice PDF to the mailbox (SMTP to GreenMail) | One mail_intake run, its PDF stored in Files, `from` the sender |
| 4 | The read scores below the floor; Maya opens Human Tasks and approves Check the debtors | The document run waited at `check`; Maya's decision is 200 |
| 5 | The approved read starts the debtor's levy run | A case opens naming the debtor as read |
| 6 | The Messaging Platform team (owner of the mail module that sends replies) approves the acknowledgement | One reply in Mailpit, from the mailbox's own address, and the document run ends `replied` |
| 7 | The same message bytes are delivered again | No second intake run |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-245-ui.mjs` | passing |

## Non-vacuous check

Step 7 is the dedupe check: it failed while the script rebuilt the PDF for the second send (a new message reusing the
Message-ID runs, by design, c-231), and passes when the same bytes are redelivered. Step 2's self-approval 403 is the
review gate's refusal paired with Priya's approval. Steps 3 to 7 failed while the harness started the worker without
`OPS_FILES_URL` (the trigger left the mailbox unread), which `packages/usecase-runner/src/harness.ts` now passes.

## What this does not cover

The real model reads the notice in `make demo-mailbox` on the shared stack (green on 2026-10-18 with gpt-5-mini); this
use case runs on the fake. A Microsoft 365 mailbox is covered by tools and agents tests against a fake Graph (c-228).
