# Mailbox demo

Status: current, 2026-10-19. The shared-stack runbook below is walked by `make demo-mailbox` (green 2026-10-18). The
walk from your own inbox at the end has not been walked yet: it needs a real mailbox connected on the shared stack.

An emailed levy notice becomes levy cases, Human Tasks and a reply, on the shared stack and a real OpenAI model.

1. `make up` starts the database, mail (GreenMail, Mailpit), every service, the workflow worker, models-service and
   the fakes, signs people in through platform-service, binds the `default` model alias to real OpenAI gpt-5-mini (the
   key from .env; `DEMO_MODEL=` picks another, `DEMO_MODEL=fake` keeps the fake) and prints a health table.
2. `make demo-mailbox` emails a notice with a PDF attached to intake@northfield.test and prints PASS or FAIL for each
   step: run started, attachment in Files, fields read, levy cases, case opened, the acknowledge Human Task, the
   reply in Mailpit.
   Each run sends a new message, so it can be repeated. `make demo-mailbox LOW=1` sends a scan of the notice instead:
   it is read by OCR, every field falls below the floor, and a "Check the debtors read" Human Task comes before any case.
3. Show the result. Sign in at <http://localhost:3016> as m.okafor@northfieldbank.com (password `northfield-demo`):
   Cases (one high-priority case per debtor, "Levy notice: <name> (<court case>)"), Workflows > Runs (the run URL is
   printed last), Human Tasks (one "Levy notice" per matched debtor), Files (the PDF)
   and the reply at <http://localhost:8025>.
4. A FAIL on `stack` names what is down; run `make up` again and `make logs SVC=<name>` for the service.

## Levy mail, mixed kinds

The levy demo (2026-10-18 plan): one email carrying two restraining notices and a tax levy. Each attachment is read in
its own run of `levy_read_one`, in parallel; the kind is detected, a doubtful read goes to a person, each kind is worked
out with a Calculate step, a case opens, and the outside system is told by webhook. Seeded workflows: `levy_mail`
(Email received on `levies@northfield.test`), `levy_read_one`, and `levy_files` (the same handling from uploaded files).

1. Send the email: from `services/agents-service`,
   `uv run python scripts/send_levy_email.py --fixture ../documents-service/tests/fixtures/mail/mixed_levies.json --mailbox levies@northfield.test --key-suffix run-2`.
   Change `run-2` for each send: the trigger keys a run on the message's ID and content, so the same email sent again
   is recorded as a duplicate and starts nothing.
2. Within a minute, Workflows > Runs shows one `levy_mail` run waiting at "Reply to service@process.example" and three
   `levy_read_one` runs, one per attachment, started together. Cases shows "Restraining notice: Parker Demo
   (SYN-2026-0006)", "Restraining notice: Sage Prototype (SYN-2026-0012)" and "Tax levy: Riley Fixture
   (SYN-TL-2026-0101)"; the bank stand-in's webhook page (`https://<this machine's address>:8745/webhooks`) lists one
   `levy.processed` payload per document, the tax levy's with its amount (7482.19) and days to respond (21).
3. Approve the reply on Human Tasks. The reply goes out through `send_reply` on the Messaging Platform team's mail
   module, so a person with that team's approval rights decides it: replies are a separate approval from the levy work.
   On the shared stack everyone is seeded admin of every team, so anyone can; on a real workspace it is that team.
4. Workflows > `levy_files` > Run with files starts the same per-document handling from uploaded files.

Proven on the shared stack with the real model on 2026-10-19: parent `wfrun_3cc2578b2ace` replied; children
`wfrun_932fbf825e7a`, `wfrun_3a7e483f1411`, `wfrun_5c4583d0b3d8` read in parallel (all started at 02:13:53.01, done by
02:14:29); cases `case_eb421c2d01cb`, `case_cb80953944b3`, `case_d01f51c35418`; webhooks `WHK-3f85eee7`, `WHK-cea464ac`,
`WHK-684e10e1`.

## From your own inbox

This is the same path with a real mailbox instead of GreenMail. Each step below is proven on an isolated stack by
uc-245 (`make usecase-test UC=uc-245 LAYER=ui ISOLATED=1`, 10 checks passing); what is new here is the mailbox.

Before you start: a Gmail address with 2-step verification and an app password
(<https://myaccount.google.com/apppasswords>), or a Microsoft 365 mailbox with an app registration that has Mail.Read
and Mail.Send. Keep the notice PDF to hand: `services/agents-service/tests/fixtures/mailbox/levy_notice.pdf`.

| # | Who and where | What you do | What you see |
|---|---|---|---|
| 1 | Sam (Security admin), Settings > Secrets | Add the app password as a secret for Operations, e.g. `DEAN_GMAIL_APP_PASSWORD` | The secret listed, value hidden |
| 2 | Sam, Settings > Egress | Allow `imap.gmail.com` and `smtp.gmail.com` | Both hosts allowed |
| 3 | James (builder), Channels > Email > Connect mailbox | Gmail, your address, the secret; replies by SMTP from the same address and secret; Test connection | Every test step passes, with your newest message's sender and subject |
| 4 | James, Workflows > Levy intake | Pick your mailbox in the Email received trigger, save, request publish | A publish review waits |
| 5 | Priya (admin), Human Tasks | Approve the publish review | The workflow is live on your mailbox |
| 6 | You, your own mail app | Email the notice PDF to your address | Within a minute: a run in Workflows > Runs, the PDF in Files |
| 7 | Maya, Human Tasks | If the read was doubtful, check and approve it; then the case appears in Cases | One case per debtor |
| 8 | An approver of the mail module, Human Tasks | Approve "Acknowledge the document" | The reply arrives in your inbox from your own address |

If a step fails, the Activity page filtered to the mailbox shows the email and why it was skipped, and
`make logs SVC=worker` names a mailbox the worker could not read.

## On Fly staging

Status: walked end to end on 2026-10-20 with an Ethereal mailbox. The notice came in through Ethereal and started
the intake run, then the document run: the PDF in Files, a read of 3 debtors, 3 cases, the Human Tasks, the
acknowledgement, and the reply from the Ethereal address to the made-up court address, found in the Ethereal
mailbox over IMAP. `mailbox_demo.py walk` does the authenticated send and the IMAP check (`--send-user`,
`--read-imap`), and the command below passed every step as written on 2026-10-20. A Gmail or Microsoft 365
mailbox follows steps 2 to 9 below, done by a person.

The walk against Ethereal, with the account's password in an environment variable and never on the command line
(the owner creates the account; the password is never written to a file in the repo):

```
export DEMO_MAILBOX_PASSWORD=...   # the Ethereal account's password
uv run python deploy/fly/staging/mailbox_demo.py walk --origin https://<your-app>-web.fly.dev \
  --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \
  --mailbox <account>@ethereal.email --imap imap.ethereal.email:993 --smtp smtp.ethereal.email:587 \
  --send-smtp smtp.ethereal.email:587 --send-user <account>@ethereal.email --read-imap imap.ethereal.email:993
```

It prints PASS or FAIL per step and exits with the number of failures. Ethereal keeps every message its SMTP accepts
in the account's mailbox, so the reply to the made-up court address is found there.

Staging is <https://<your-app>-web.fly.dev>. `deploy/fly/staging/mailbox_demo.py seed` ran on 2026-10-20 and
printed this state:

| What | State |
|---|---|
| Mail poller | The worker app (`<your-app>-worker`, started with `gateway=True`) reads every mailbox connected on Channels > Email |
| Egress | `imap.gmail.com`, `smtp.gmail.com`, `outlook.office365.com`, `smtp.office365.com`, `graph.microsoft.com`, `login.microsoftonline.com` and the bank stand-in are allowed |
| Ethereal | Staging's test mailbox (<https://ethereal.email>). `imap.ethereal.email` (IMAP 993) and `smtp.ethereal.email` (SMTP 587, STARTTLS) allowed on 2026-10-20 by `mailbox_demo.py egress`, read back from the allow-list. The owner creates the account and enters its address and password on Channels > Email; nobody else creates it or handles the password. The levy notice is sent to it through `smtp.ethereal.email`, and replies are read in Ethereal's web inbox. Not walked yet |
| Platform tools | A production install has no dev seed, so no module held `send_reply` and the reply step failed with "tool send_reply is not registered with the gateway". tools-service now writes a tenant's Platform tools module (`mod_platform_tools`: `send_reply` and `open_case`, run in process, owned by the install's Security team) the first time a call or a grant list needs a platform tool no module holds (`ops_tools.modules.seed.ensure_platform_tools`). Staging's copy, written by hand on 2026-10-20 with the same id, is kept as it is |
| Bank stand-in | `<your-app>-bank`, synthetic customers only, imported as tool module `mod_3a1fdc1ba8a4` (12 operations, version 2.0.0 published); holds wait for a person. `/openapi.json` answers 200 and `/customers` without the key answers 401 |
| Document types | levy notice, restraining notice, tax levy, supplier invoice, bank statement |
| Workflows | `levy_case`, `mail_document`, `levy_read_one` live; `mail_intake` (Mailed documents) and `levy_mail` saved as drafts until a mailbox is picked |
| Model | Not checked. `deploy/fly/staging/apps.py` makes the fake model (`<your-app>-fake`) staging's only model connection; whether `default` and `extract` were rebound to OpenAI through the secret name `OPENAI_API_KEY` could not be read, since reading the aliases needs `deploy/fly/connect_model.py` on the agents machine and SSH into the staging Fly org is refused. On the fake model the reads answer from its committed rules and step 2 below is not needed |
| Team | Everything is in the first team (Security): tools-service only knows the install's own team ids, so a team made on the Teams page cannot own the bank module yet |
| People | The admin, and `approver@<your-app>.example` (an approver in Security, for the two-person publish reviews) |
| Mailboxes | None connected. Channels > Email is empty, so the worker's listener has nothing to read |

Before you start: a Gmail address with 2-step verification and an app password
(<https://myaccount.google.com/apppasswords>), or a Microsoft 365 mailbox with IMAP and SMTP AUTH allowed; an OpenAI
API key if the aliases point at OpenAI (see Model above); `services/agents-service/tests/fixtures/mailbox/levy_notice.pdf`. The admin's sign-in is in
`~/.config/ops-ai/staging-admin.env`, the second person's (an approver) in `~/.config/ops-ai/staging-demo-people.env`.

| # | Where | What you do | What you see |
|---|---|---|---|
| 1 | Sign in as the admin | | Overview |
| 2 | Settings > Secrets | Only if the aliases point at OpenAI: add `OPENAI_API_KEY` (all teams) with your OpenAI key | The secret listed, value hidden |
| 3 | Settings > Secrets | Add `DEMO_MAILBOX_PASSWORD` for Security with the app password | The secret listed |
| 4 | Channels > Email > Connect mailbox | Gmail: your address and `DEMO_MAILBOX_PASSWORD`; replies by SMTP `smtp.gmail.com` port 587 with STARTTLS and the same secret (Microsoft 365: `outlook.office365.com` 993, `smtp.office365.com` 587). Test connection | Every test step passes, with your newest message's sender and subject |
| 5 | Workflows > Mailed documents | Pick your mailbox in the Email received trigger, save, request publish | A publish review waits |
| 6 | The second person, Human Tasks | Approve the publish review (a private window) | Mailed documents is live on your mailbox |
| 7 | Your own mail app | Email `levy_notice.pdf` to your address | Within a minute: a run in Workflows > Runs, the PDF in Files |
| 8 | Cases and Human Tasks | One case per debtor; a matched debtor waits on a "Levy notice" task (hold or flag) | The cases and tasks |
| 9 | Human Tasks | Approve "Acknowledge the document" | The reply arrives in your inbox from your own address |

Steps 5 and 6 can be done in one go instead:
`uv run python deploy/fly/staging/mailbox_demo.py seed --origin https://<your-app>-web.fly.dev --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env --bank https://<your-app>-bank.fly.dev --bank-env ~/.config/ops-ai/staging-bank.env --mailbox <your address>`.

If nothing arrives: `fly logs -a <your-app>-worker` names a mailbox the worker could not read, and the Activity
page filtered to the mailbox shows the email and why it was skipped. Use one mailbox per Email received workflow: a
mailbox bound to both Mailed documents and `levy_mail` starts both on every email.
