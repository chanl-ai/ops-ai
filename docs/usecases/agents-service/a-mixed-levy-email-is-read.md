# A mixed levy email is read by kind

Status: passing (2026-10-19). Id: `uc-246`. Service: `agents-service`. Layers: ui. The levy demo (2026-10-18).

One email carries levy documents of different kinds. `levy_mail` reads each attachment in its own run of
`levy_read_one`, in parallel: the kind is detected (Extract with Detect), a doubtful read waits for a person, each kind
is worked out with a Calculate step, a case opens, and the outside system is told by webhook through the tools
gateway. The sender gets a reply once acknowledged. Nothing is faked but the bank and the model; the fake model's
answers for these files replay the shared stack's real run of 2026-10-19 (`docs/console/mailbox-demo.md`).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA, GreenMail and Mailpit for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-246 LAYER=ui ISOLATED=1` |

The stack is the banker demo with the seeded mailboxes (`levies@northfield.test` for `levy_mail`), GreenMail and
Mailpit reachable through tools-service (`tools.mail`), and the bank stand-in that records webhooks
(`stack.bank.url/webhooks.json`).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Sam puts the mailbox password on the Secrets page and allows the mail hosts | 201 for each |
| 1 | worker-x's mixed email (two restraining notices, a tax levy) plus a second tax levy arrives at `levies@northfield.test` | One `levy_mail` run waiting to reply, and one `levy_read_one` run per attachment |
| 2 | The four reads | From the first start to the last finish took less time than the reads one after another: they ran in parallel |
| 3 | Detection and routing | TEST006 ends `restraining_notice`, TAXLEVY01 `tax_levy`; TEST012 and TAXLEVY02 wait at Check the read |
| 4 | Maya approves both checks on Human Tasks | Each run continues to its kind and ends `restraining_notice` / `tax_levy` |
| 5 | Cases and terms | One case per document named from the read (`Restraining notice: Parker Demo (SYN-2026-0006)` and so on); TAXLEVY01's Calculate gives amount 7482.19 and 21 days to respond |
| 6 | The webhook stand-in | One `levy.processed` payload per case |
| 7 | The Messaging Platform team acknowledges | The parent ends `replied` and one more reply from `levies@northfield.test` is in Mailpit |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-246-ui.mjs` | passing |

## Non-vacuous check

Step 2 compares the reads' overall span with the sum of their durations, so a worker that ran the children one after
another fails it. On the shared stack with the real model all three reads overlapped completely (02:13:53.01 to
02:14:29).
Step 7 counts replies before and after the acknowledgement, so a reply left by an earlier run does not pass it.
