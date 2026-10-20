# An email in an IMAP mailbox starts a workflow

Status: current. Id: `uc-192`. Service: `agents-service`. Layers: api. Card: c-192.

A team mailbox read over IMAP, its password a Secrets-page secret that only tools-service reads. The worker asks
tools-service's `/v1/mailboxes` for new mail (IDLE, with the poll as fallback) and starts one run per matching message,
attachments in Files first. GreenMail in compose plays the mailbox; a real Gmail mailbox follows
`docs/packages/ops_email/test-with-gmail.md`.

## Preconditions

| Needs | How |
|---|---|
| The shared stack with platform sign-in, GreenMail and Mailpit | `OPS_STACK_AUTH=platform make up` |
| `intake@northfield.test` in the mailbox settings | `scripts/stack.sh` (IMAP on `mail.northfield.test`, secret `DEV_IMAP_PASSWORD`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam adds the secret for team_ops, the host `mail.northfield.test` and this machine's address as a range | 201, or 200/409 when already there |
| 2 | James opens the mailbox picker | `intake@northfield.test` shows as `team_ops · IMAP` |
| 3 | James saves and publishes a workflow bound to it | 201 |
| 4 | Mail sent before the first pass | No run |
| 5 | An email with a PDF sent to GreenMail over SMTP | One run within seconds; the PDF as a Files id |
| 6 | Read the file as James | The PDF's bytes |
| 7 | The same Message-ID again | No second run |
| 8 | The secret's record | `lastUsedAt` set; no response carried the password |

Guards (allow-list, team scope, `deployments:run`, plain IMAP) are `services/tools-service/tests/test_mailboxes.py`;
first pass and IDLE are `services/agents-service/tests/engine/test_email_trigger_imap.py`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-192-api.py` | passing |

## Non-vacuous check

Each guard and rule removed alone turns its test red: `.codeloop/evidence/192/`.
