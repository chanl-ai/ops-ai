# Test the email trigger with a real Gmail mailbox

Status: current. These steps run a workflow from mail sent to a spare Gmail address on the local stack. The
IMAP path is proven on GreenMail (uc-192, uc-199); a real Gmail mailbox has not been run yet (**unverified**). If a step fails,
the log line named under "If nothing happens" says why.

## What you need

| Item | Where |
|---|---|
| A spare Gmail address with 2-Step Verification on | Google account, Security |
| An app password for it (16 letters) | <https://myaccount.google.com/apppasswords>; name it "Ops AI" |
| The local stack with platform sign-in | `OPS_STACK_AUTH=platform make up` |

## Steps

| # | Do | Where |
|---|---|---|
| 1 | Create the app password and copy it. | Google account |
| 2 | Sign in as Sam Adeyemi (`s.adeyemi@harborpine.example`, password `northfield-demo`), add a secret named `GMAIL_APP_PASSWORD` with the app password as its value, scoped to team `team_ops`. | Console, Settings > Secrets |
| 3 | Still as Sam, add `imap.gmail.com` to the allowed hosts. | Settings > Egress |
| 4 | Sign in as James Richardson (`j.richardson@harborpine.example`). Open Channels, press **Connect a mailbox**, pick **Gmail**, then give it a name, the Gmail address and `GMAIL_APP_PASSWORD` as the app password. | Console, Channels > Email (`http://localhost:3016/channels/email`) |
| 5 | Press **Test connection**. It should say Connected and show the newest subject in the inbox. Then press **Connect mailbox**. | The connect form |
| 6 | Create a runner workflow, open its trigger, pick **Email received** and choose the Gmail mailbox (the picker says Gmail; **Connect a mailbox** there opens the same form). Set filters if you want them, save the version and publish it; approve the publish request in Reviews if your team requires one. | Console, Workflows |
| 7 | Wait a few seconds after publishing: the first pass takes the inbox as it is, so mail already there starts nothing. | |
| 8 | From another account, send an email with a PDF to the Gmail address. | Any mail client |
| 9 | A run appears on the workflow's Runs tab within seconds (IDLE), and the PDF is in Files. The mailbox's page lists the workflow and when it was last read. | Console |

No settings file is edited and nothing restarts: the mailbox is a record the worker reads on its next pass.

## If nothing happens

| Sign | Means | Fix |
|---|---|---|
| Test connection names the allow-list, or `egress_denied` in `make logs SVC=worker` | `imap.gmail.com` is not an allowed host | Step 3 |
| Test connection names the secret, or `secret_refused` | The secret is missing or not scoped to team_ops | Step 2 |
| `AUTHENTICATIONFAILED` | Wrong app password, or 2-Step Verification is off | Step 1, then rotate the secret |
| `email_binding_refused` in the worker log | The workflow does not belong to the mailbox's team | Save the workflow while acting in team_ops |
| The mailbox shows Paused | Someone paused it | Resume it on its page |

The password stays in tools-service: it is read from the Secrets page at each read and never sent to the worker or
the console.
