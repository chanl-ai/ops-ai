# A builder connects a team mailbox and binds a workflow to it

Status: current. Id: `uc-199`. Service: `agents-service`. Layers: api, ui. Card: an earlier change.

A team mailbox is a record on Channels > Email (agents-service `/v1/channels/mailboxes`), not a settings line: a
builder connects it with a Secrets-page secret as its password, tests it, and picks it in a workflow's Email received
trigger, with no restart. tools-service reads Gmail and IMAP mailboxes with the secret looked up for the mailbox's team.

## Preconditions

| Needs | How |
|---|---|
| api: the shared stack with platform sign-in, GreenMail and Mailpit | `OPS_STACK_AUTH=platform make up` |
| ui: an isolated stack | `ISOLATED=1 make usecase-test UC=uc-199 LAYER=ui` starts its own |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Ravi (viewer) connects a mailbox | 403 |
| 2 | James tests the unsaved form | Connected, with the newest subject from GreenMail |
| 2b | James connects a Microsoft 365 mailbox: tenant id, client id, the client secret from Secrets, replies through Microsoft 365, and tests it | The form asks for no IMAP server, user name or from address; the test shows the server's answer; the saved mailbox is a Microsoft 365 one with those ids, that secret and Graph replies |
| 3 | James connects it | 201; it is listed for team_ops; Omar (team_fraud) gets 404 on it |
| 4 | James opens the trigger's mailbox picker | It is offered |
| 5 | James binds a workflow, pauses the mailbox, mail arrives | No run while paused |
| 6 | James resumes it | The mail that arrived meanwhile starts one run; the page lists the workflow and its last read |
| ui 1 | Channels > Email | The seeded mailboxes are listed |
| ui 2 | Connect an IMAP mailbox, Test connection, Connect | The test shows the server's answer; the mailbox's page opens |
| ui 3 | On the canvas, the Email received trigger's Connect a mailbox | The new mailbox fills the trigger; the saved version names it |

Route rules are `services/agents-service/tests/api/test_channel_mailboxes.py`; tools-service's guards are
`services/tools-service/tests/test_mailboxes.py`; pause is `tests/engine/test_email_trigger.py`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-199-api.py` | passing |
| ui | `agents-service/scripts/test-uc-199-ui.mjs` | passing |

## Non-vacuous check

Each route rule removed alone turns its test red.
