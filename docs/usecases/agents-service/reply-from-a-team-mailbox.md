# A reply leaves from the team mailbox the customer wrote to

Status: current. Id: `uc-200`. Service: `agents-service` (mailbox records) and `tools-service` (send_reply). Layers:
api. Card: an earlier change.

A mailbox on Channels > Email carries the sender its replies go out through: SMTP or Resend, a from address and a
Secrets-page secret. A `send_reply` that names the mailbox sends through it, for the calling team only.

## Preconditions

| Needs | How |
|---|---|
| The shared stack with platform sign-in, GreenMail and Mailpit | `OPS_STACK_AUTH=platform make up` |
| `smtp.harborpine.test` answered with Mailpit's SMTP | `scripts/stack.sh` sets it on tools-service (dev only) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Sam (Security) adds the secret for team_ops and lists the SMTP host | Saved |
| 1 | James connects a mailbox whose replies go through SMTP at `smtp.harborpine.test` | 201; its page shows the sender |
| 2 | A workflow call of team_ops sends `send_reply` naming the mailbox, with an approval token | Sent; Mailpit has it from the mailbox's from address |
| 3 | The same call again (same key) | Replayed; Mailpit still has one copy |
| 4 | The same reply as a team_fraud call | Not sent; the reason says it is not team_fraud's mailbox |

Rules are `services/tools-service/tests/test_mailbox_senders.py`.

In the console: uc-245's ui script: the acknowledgement is approved in Human Tasks and the reply leaves from the mailbox's own address. Another team's call has no console surface.
