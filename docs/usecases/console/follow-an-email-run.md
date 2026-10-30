# Follow an email from arrival to every case it opened

Status: current. Id: `uc-477`. Service: `console` on agents-service, files-service and documents-service. Layers: ui. Card: an earlier change.

A person opens an email-started run and reads what happened without JSON. The run page tells the run from its steps'
output shapes (`story` on `GET /v1/runs/{id}`): the email it began with, each document a read step read beside the
document with the fields boxed, and one row per run its steps started with what that run was about, where it is now,
its case and its Human Task. A run it started has its own page for what it read and started in turn. The use case runs
copies of the seeded court order notice workflows (`mail_intake`, `mail_document`, `levy_case` in
`services/agents-service/seed/engine_workflows.json`) on the demo stack with a worker, so the fake model's committed
read of `levy_notice.pdf` names three debtors and the core fake bank matches two of them.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts the intake copy with Start run → Send a test email, attaching `levy_notice.pdf` | The run starts (202) |
| 2 | He opens the email run's page | The Email section shows from, subject, text and the attachment; one row for the attachment's run, named `levy_notice.pdf`; no JSON block in the result |
| 3 | Maya approves the read check through the API; James opens the attachment row's run | The read shows beside the document: three record tabs (Marcus Bell, Priya Natarajan, Jordan Whitfield) and at least nine field boxes on the page |
| 4 | He reads the runs that run started | Three rows named by debtor, each with Case and Human Task links; Marcus's row names his customer and accounts and "Hold or flag · waiting for the team" |
| 5 | He reads Jordan Whitfield's row | "Waiting for a person", case "No customer matched: Jordan Whitfield (MB-2026-GN-00318)", task "Find the customer or close as not ours" |
| 6 | Every page at 1280 and 400 px | No page errors and no sideways scroll |

Screenshots are saved under `evidenceDir('477', 'uc')` (the use-case runner's harness). Set `OPS_USECASE_DB` to a fresh name
when the shared `ops_usecase` database holds rows an older checkout wrote.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-477-ui.mjs` | passing |

## Non-vacuous check

Run before the change (at fda74a2f), steps 2 to 5 failed: no Email section, no rows named by debtor, no read on the
document run's page, Jordan Whitfield ending with no task (card an earlier change's red run). With the change all
six pass (its green run).
