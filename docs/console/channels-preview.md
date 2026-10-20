# Channels mock

Status: current (design mock; nothing in it is stored, and no live page or route reads it).

The owner asked for a workspace Channels app and for how a workflow's Email received trigger reaches a connected
mailbox. `/preview/channels` draws both on sample data, on a development server only (`src/proxy.ts` answers 404
elsewhere). The walk is use case `uc-165` (`docs/usecases/console/channels-preview.md`).

## What the mock shows

| Route | What it is |
|---|---|
| `/preview/channels` | One card per channel kind (Email mailbox, Chat embed and API built; MCP, Slack and Teams coming soon) and every connection with status, last activity and the workflows using it. A mailbox row opens its settings drawer |
| `/preview/channels/email`, `/email/connect`, `/email/<id>` | The mailboxes, the connect form as a page, and one mailbox: status, last message, workflows bound to it with links |
| `/preview/channels/chat`, `/api` | Connections of that kind; they link to where each is made (an agent's Channels tab, Team › API keys) |
| `/preview/channels/trigger` | A mock of the canvas's trigger sheet: Email received picks a connected mailbox, and Connect a mailbox opens the same connect form as a dialog |
| Channel tabs | Every page carries a tab per kind with a dot: receiving, needs attention or not set up; kinds coming soon have none |
| A kind's landing | What it does, its state, what it includes, and its 7-day activity count with View activity, which opens the Activity page filtered to it |
| Serves, in place | Each connection names the workflow or agent it serves and the version: the latest published one or a pinned one, changed from the row |
| `/preview/channels/agent` | Advisor's Helper's Channels tab as a table: where it answers, the version live there, status and 24-hour traffic, with a versions summary |
| `/preview/channels/activity` | The one Activity page (runs, chats, emails, tool calls, decisions) with kind, status, channel and source filters |
| `/preview/deployments` | Lands on Channels: Deployments fold into Channels, and versions stay on the agent and the workflow |

The connect form is one component in two shells (`_parts/connect-mailbox.tsx`): pick Gmail, Microsoft 365 or other
IMAP, then sign-in, folder, a test and the replies sender (`_parts/mailbox-fields.tsx`, also the drawer's form).
Credentials are never typed into the channel: each field names a secret picked from, or added to, the Secrets list
(the settings mock's `SecretForm`). The agent's Channels tab (c-130) is unchanged and linked from the mailbox.

## Server routes the real build needs

| Route | Today | Needed for |
|---|---|---|
| `GET /v1/channels` | none; mailboxes are `OPS_EMAIL_MAILBOXES` in agents-service settings (c-187, c-192) | The list, joined in the service with status, last activity, last message and the workflows bound to each, so the page makes one call |
| `POST /v1/channels/mailboxes`, `PATCH /v1/channels/mailboxes/{id}` | none; mailboxes change by editing settings | Connect and edit: provider, address, IMAP host or Graph tenant and client, the password's secret name (c-192's `passwordSecret`), folder, team |
| `POST /v1/channels/mailboxes/{id}/test` and the same on an unsaved body | tools-service `POST /v1/mailboxes/read` reads an IMAP mailbox for agents-service with a service token | Test connection: sign in, list folders, read the newest message without marking it read, the reason on failure |
| `PATCH /v1/channels/{id}` with `paused` | `PATCH /v1/deployments/{id}` pauses a v1 deployment, not a mailbox | Pause and resume |
| `GET /v1/workflows/option-sources?source=mailboxes` | built (c-187, `routers/engine.py`) from settings | The trigger's picker; it reads the channels list once that exists |
| Bind | the live version's trigger node names the mailbox in `parameters.mailbox`; publishing binds it (c-187) | c-194 proposes `trigger_bindings` records, which give the mailbox page its workflow list without scanning definitions |

The replies sender is per process today (`OPS_MAIL_PROVIDER`, `OPS_MAIL_FROM`, `packages/ops_email`). The mock puts a
sender on each mailbox (SMTP, Resend or Microsoft 365, with its secret by name), which needs `EmailProviders` to build a
sender from a mailbox's settings as it already builds a source.
