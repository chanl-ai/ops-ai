# Mailbox demo

Status: current, 2026-10-20. The shared-stack runbook below is walked by `make demo-mailbox` (green 2026-10-18). The
walk from your own inbox at the end has not been walked yet: it needs a real mailbox connected on the shared stack.

An emailed court order notice (a court or authority ordering the bank to hold or pay a customer's funds) becomes
cases, Human Tasks and a reply, on the shared stack and a real OpenAI model.

1. `make up` starts the database, mail (GreenMail, Mailpit), every service, the workflow worker, models-service and
   the fakes, signs people in through platform-service, binds the `default` model alias to real OpenAI gpt-5-mini (the
   key from .env; `DEMO_MODEL=` picks another, `DEMO_MODEL=fake` keeps the fake) and prints a health table.
2. `make demo-mailbox` emails a notice with a PDF attached to intake@northfield.test and prints PASS or FAIL for each
   step: run started, attachment in Files, fields read, court order cases, case opened, the acknowledge Human Task, the
   reply in Mailpit.
   Each run sends a new message, so it can be repeated. `make demo-mailbox LOW=1` sends a scan of the notice instead:
   it is read by OCR, every field falls below the floor, and a "Check the debtors read" Human Task comes before any case.
3. Show the result. Sign in at <http://localhost:3016> as m.okafor@northfieldbank.com (password `northfield-demo`):
   Cases (one high-priority case per debtor, `Levy notice: <name> (<court case>)`), Workflows > Runs (the run URL is
   printed last), Human Tasks (one `Levy notice` task per matched debtor), Files (the PDF)
   and the reply at <http://localhost:8025>.
4. A FAIL on `stack` names what is down; run `make up` again and `make logs SVC=<name>` for the service.

## Court order mail, mixed kinds

The court order demo (2026-10-18 plan): one email carrying two restraining notices and a tax authority's order. Each
attachment is read in its own run of the court order read workflow (`levy_read_one`), in parallel; the kind is
detected, a doubtful read goes to a person, each kind is worked out with a Calculate step, a case opens, and the outside
system is told by webhook. Seeded workflows: the court order mail workflow (`levy_mail`, Email received on
`levies@northfield.test`), `levy_read_one`, and `levy_files` (the same handling from uploaded files).

1. Send the email: from `services/agents-service`,
   `uv run python scripts/send_levy_email.py --fixture ../documents-service/tests/fixtures/mail/mixed_levies.json --mailbox levies@northfield.test --key-suffix run-2`.
   Change `run-2` for each send: the trigger keys a run on the message's ID and content, so the same email sent again
   is recorded as a duplicate and starts nothing.
2. Within a minute, Workflows > Runs shows one `levy_mail` run waiting at "Reply to service@process.example" and three
   `levy_read_one` runs, one per attachment, started together. Cases shows "Restraining notice: Parker Demo
   (SYN-2026-0006)", "Restraining notice: Sage Prototype (SYN-2026-0012)" and the tax order's case
   `Tax levy: Riley Fixture (SYN-TL-2026-0101)`; the bank stand-in's webhook page
   (`https://<this machine's address>:8745/webhooks`) lists one `levy.processed` payload per document, the tax order's with its amount (7482.19) and days to respond (21).
3. Approve the reply on Human Tasks. The reply goes out through `send_reply` on the Messaging Platform team's mail
   module, so a person with that team's approval rights decides it: replies are a separate approval from the court order work.
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
| 4 | James, Workflows > the court order intake workflow (`Levy intake`) | Pick your mailbox in the Email received trigger, save, request publish | A publish review waits |
| 5 | Priya (admin), Human Tasks | Approve the publish review | The workflow is live on your mailbox |
| 6 | You, your own mail app | Email the notice PDF to your address | Within a minute: a run in Workflows > Runs, the PDF in Files |
| 7 | Maya, Human Tasks | If the read was doubtful, check and approve it; then the case appears in Cases | One case per debtor |
| 8 | An approver of the mail module, Human Tasks | Approve "Acknowledge the document" | The reply arrives in your inbox from your own address |

If a step fails, the Activity page filtered to the mailbox shows the email and why it was skipped, and
`make logs SVC=worker` names a mailbox the worker could not read.

## On Fly staging

Status: current, 2026-10-20 (c-406). Staging is the one-machine app <https://<your-app>-one.fly.dev>
(`docs/deploy/fly-staging.md`); it sleeps when idle and the first request takes about 35 s. Every step after the
inbound email is walked on it with the real model: the notice read, a case per debtor, the hold approved and placed at
the bank stand-in, the unmatched debtor's own case, the acknowledgement and the reply sent from the connected test
mailbox. The worker reads that mailbox: it picked up the reply the platform sent from it within seconds. An email
with the notice attached, sent from outside, has not been walked on this app yet: sending to the test mailbox and
reading its reply need its password, which is held only in Secrets.

| What | State |
|---|---|
| Mailbox | The Ethereal test account is connected in Security (Channels > Email, "Demo intake"), its password the secret `DEMO_MAILBOX_PASSWORD`; Test connection passes. A workspace connects an address once and a mailbox cannot be removed or moved to another team yet (proposed c-421), so the test account stays in Security |
| Workflows | Security: `mail_intake` (Mailed documents) v2 live on the test mailbox, starting `mail_document` per attachment, which starts `levy_case` per debtor |
| Demo team | Northfield Operations (`team_a0877a1d8907`): the garnishment notice type and the court order workflows `levy_document_a0877a1d` (`Levy notice: read the document`) and `levy_debtor_a0877a1d` (`Levy notice: one debtor`), live, made by `mailbox_demo.py levy` from `scripts/demo/team.json`. Workflow and document type ids are one per workspace, so a team's copies end in its id's first eight characters. No mailbox yet, so the email intake `levy_mail_intake_a0877a1d` is made when one is connected |
| Model | The read uses alias `extract`, or `default` when there is none. Staging has no `extract`, so `default` serves it: gpt-4.1-mini on OpenAI, key `OPENAI_API_KEY` in Secrets, through models-service key `purpose:documents` (cap 5 USD). One real model call per notice |
| Bank stand-in | `<your-app>-bank`, its public URL; holds wait for a person. Its holds live in memory, so they last until the machine restarts: Marcus Bell's chequing account holds 2,140.55, so after one hold on it a second one fails. Restart it before a demo with `fly machine restart 185d5e7bd3d548 -a <your-app>-bank` (restarted after the last walk on 2026-10-20). The walk flags an account with nothing free |
| Files | The PDFs uploaded before the move to one machine were copied from the stopped files app's volume on 2026-10-20, so the notice opens on the task page |
| Egress | Gmail, Microsoft 365 (IMAP, SMTP, Graph and its sign-in), Ethereal and the bank stand-in are allowed |

### Set a team up

`mailbox_demo.py levy` puts the court order story in a team: egress for the mail providers and the bank stand-in, the
garnishment notice document type, and the court order workflows from `scripts/demo/team.json`, each published through the
second person (who joins the team as an approver). With `--mailbox`, a mailbox already connected in the team, it also
makes the email intake on that mailbox. Re-runnable: what exists is reported FOUND.

```
uv run python deploy/fly/staging/mailbox_demo.py levy --origin https://<your-app>-one.fly.dev \
  --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \
  --team team_a0877a1d8907 [--mailbox <address connected in the team>]
```

Walked in Northfield Operations on 2026-10-20 after a bank restart, every step PASS (`--upload`, no mailbox, so the
acknowledgement is declined and the run ends `cases_opened`): document run `wfrun_8555bc8848e2`; `case_a38950954252`
Marcus Bell, hold `HLD-7c4ac0` of 2,140.55 on `CHQ-2219`; `case_e3171dca2ac6` Priya Natarajan, hold `HLD-30152d` of
12,400.00 on `BUS-7781`, both found at the bank; `case_e9f19b9569b7` Jordan Whitfield, no bank customer. Command:
the upload walk below with `--team team_a0877a1d8907 --document-workflow levy_document_a0877a1d` and no `--mailbox`.

### The walk

`deploy/fly/staging/mailbox_demo.py walk` sets the mailbox up in a team as a person would (the secret usable by the
team, the hosts on the egress list, Connect mailbox and Test connection, the team's Email received workflow pointed at
it and published by a second person), sends the notice, and checks every step through the API, printing PASS or FAIL
and exiting with the number of failures. It is re-runnable, and `--team` with `--intake-workflow` (and
`--document-workflow` when the intake is new to the team) run it in any team. Without the mailbox password,
`--upload` starts the document run from the uploaded notice instead of an email:

```
uv run python deploy/fly/staging/mailbox_demo.py walk --origin https://<your-app>-one.fly.dev \
  --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \
  --mailbox <account>@ethereal.email --imap imap.ethereal.email:993 --smtp smtp.ethereal.email:587 \
  --bank-env ~/.config/ops-ai/staging-bank.env --upload
```

With the password, the same command emails the notice through Ethereal and finds the reply over IMAP. The password is
read from the environment, never from the command line or a file in the repo:

```
export DEMO_MAILBOX_PASSWORD=...   # the Ethereal account's password
uv run python deploy/fly/staging/mailbox_demo.py walk --origin https://<your-app>-one.fly.dev \
  --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \
  --mailbox <account>@ethereal.email --imap imap.ethereal.email:993 --smtp smtp.ethereal.email:587 \
  --bank-env ~/.config/ops-ai/staging-bank.env \
  --send-smtp smtp.ethereal.email:587 --send-user <account>@ethereal.email --read-imap imap.ethereal.email:993
```

Screenshots of the case, the task and the run, headless: `STG_ORIGIN=... STG_EMAIL=... STG_PASSWORD=... OUT=<dir>
node deploy/fly/staging/mailbox_demo_shots.mjs cases/<case id> reviews/<run id>:review:1 workflows/runs/<run id>`.

Walked with `--upload` on 2026-10-20, every step PASS: document run `wfrun_ae2d63cb7d1b`; cases `case_49a13613a105`
(Marcus Bell, flagged: his chequing account was already held by the walk before), `case_747e1514a0d8` (Priya
Natarajan, hold `HLD-307645` of 12,400.00 on `BUS-7781`, found at the bank) and `case_0206efee86de` (Jordan Whitfield,
no bank customer); the reply sent from the test mailbox.

### Connect your own mailbox

Your mailbox goes straight into the demo team, Northfield Operations (`team_a0877a1d8907`); a mailbox stays in the
team that connects it (c-421). Sign in to <https://<your-app>-one.fly.dev> as the admin
(`~/.config/ops-ai/staging-admin.env`) and pick Northfield Operations in the team switcher, except where a step says
Security. Keep `services/agents-service/tests/fixtures/mailbox/levy_notice.pdf` to hand. Before a demo, restart the
bank stand-in (Bank stand-in above) so each matched debtor can be held.

Gmail (IMAP and SMTP with an app password):

| # | Where | What you do |
|---|---|---|
| 1 | <https://myaccount.google.com/apppasswords> | With 2-Step Verification on, create an app password named "Ops AI" and copy the 16 letters |
| 2 | Security team, Settings > Secrets > Add secret | Name `OWNER_MAILBOX_PASSWORD`, the app password as its value, team Northfield Operations |
| 3 | Northfield Operations, Channels > Email > Connect a mailbox | Gmail; a name; your address; App password `OWNER_MAILBOX_PASSWORD`; Send replies with SMTP, from your address, SMTP password `OWNER_MAILBOX_PASSWORD`. Test connection shows your newest subject; then Connect mailbox |
| 4 | A terminal in the ops-ai repo | `mailbox_demo.py levy` as in "Set a team up", with `--mailbox <your address>`: it makes `Levy notices by email` (`levy_mail_intake_a0877a1d`) on your mailbox and publishes it through the second person |
| 5 | Another mail account | Email `levy_notice.pdf` to your address. Within a minute: a run in Workflows > Runs and the PDF in Files |
| 6 | Human Tasks | Each matched debtor's "Hold or flag": Hold, with the amount (up to what the account has free). Then "Send the acknowledgement": Approve. The reply reaches the account you sent from |

Microsoft 365 (Microsoft Graph with an app registration; Exchange Online refuses basic sign-in over IMAP and SMTP, so an
app password does not work there). The Graph mailbox is tested against a stand-in only and has not run against a real
tenant (**unverified**):

| # | Where | What you do |
|---|---|---|
| 1 | Microsoft Entra admin center > App registrations > New registration | Name it "Ops AI staging"; copy the Directory (tenant) id and the Application (client) id |
| 2 | The registration > API permissions | Microsoft Graph, Application permissions: `Mail.Read` and `Mail.Send`; Grant admin consent. These reach every mailbox in the tenant unless an Exchange application access policy limits them to yours |
| 3 | The registration > Certificates & secrets | New client secret; copy its value |
| 4 | Security team, Settings > Secrets > Add secret | Name `OWNER_GRAPH_SECRET`, the client secret as its value, team Northfield Operations |
| 5 | Northfield Operations, Channels > Email > Connect a mailbox | Microsoft 365; a name; your address; Microsoft tenant id; Client id; Client secret `OWNER_GRAPH_SECRET`; Send replies with Microsoft 365. Test connection, then Connect mailbox |
| 6 | As for Gmail, steps 4 to 6 | Make the email intake on the mailbox, email the notice, decide the Human Tasks |

If nothing arrives: the Activity page filtered to the mailbox lists each email and why one was skipped (an email
with no attachment is skipped by Mailed documents), and `fly logs -a <your-app>-one` lines starting `[worker]` name
a mailbox the worker could not read. One Email received workflow per mailbox: a mailbox bound to both Mailed
documents and `levy_mail` starts both on every email.
