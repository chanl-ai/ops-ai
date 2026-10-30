# Email library

Status: current. Mail in and out behind two protocols, with providers picked by settings. The Graph
provider is tested on a mock transport only; it has not run against a tenant (**unverified**).

| Part | Where | What it does |
|---|---|---|
| `MailSource` | `packages/ops_email/src/ops_email/inbound.py` | `delta(link)` pages new mail in one folder of one mailbox; `parse(item)` gives an `InboundMessage` |
| `drain` | `inbound.py` | Hands each item to the consumer and returns the next cursor only after the last page, so a poll that dies part-way starts again from the saved cursor |
| Message key | `inbound.py`, `graph.py` | Normalised Message-ID (brackets stripped, domain lower-cased), or a SHA-256 of sender, time and subject when there is none; the dedupe key for every consumer |
| `EmailFilter` | `inbound.py` | From contains, subject contains, has an attachment; case-insensitive |
| `MailSender` | `outbound.py` | `send(OutboundMessage) -> reference`; the message carries the caller's idempotency key |
| `EmailProviders` | `providers.py` | Builds the source and sender from settings once per process; a missing secret raises at start-up |

## Providers and settings

| Direction | Setting | Value | Needs |
|---|---|---|---|
| In | `OPS_MAILBOX_SOURCE` | `graph` | `OPS_GRAPH_TENANT_ID`, `OPS_GRAPH_CLIENT_ID`, `OPS_GRAPH_CLIENT_SECRET`; `OPS_GRAPH_URL` and `OPS_GRAPH_LOGIN_URL` default to Microsoft's public cloud |
| In | `OPS_MAILBOX_SOURCE` | `none` | Nothing is read; a consumer that asks for a source gets `MailboxNotConfiguredError` |
| Out | `OPS_MAIL_PROVIDER` | `smtp` | `OPS_MAIL_FROM`, `OPS_SMTP_HOST`, `OPS_SMTP_PORT`, optional `OPS_SMTP_USERNAME`, `OPS_SMTP_PASSWORD`, `OPS_SMTP_STARTTLS` |
| Out | `OPS_MAIL_PROVIDER` | `resend` | `OPS_MAIL_FROM`, `OPS_RESEND_API_KEY`; the idempotency key goes as `Idempotency-Key` |
| Out | `OPS_MAIL_PROVIDER` | `graph` | `OPS_MAIL_FROM` (the sending mailbox) and the Graph credentials above |
| Out | `OPS_MAIL_PROVIDER` | `fake` (dev only) | Each message is written to `OPS_MAIL_FAKE_OUT_DIR/<key hash>.json` |
| Out | `OPS_MAIL_PROVIDER` | `none` | Every send fails with "No mail provider is configured" |

## Consumers

| Consumer | Path |
|---|---|
| Email received trigger | `services/agents-service/src/ops_agents/api/email_trigger.py` |
| v1 mailbox channel (retires with v1 deployments) | `services/agents-service/src/ops_agents/api/channels/mailbox/adapter.py` |
| `send_reply` tool | `services/tools-service/src/ops_tools/tools.py` |

## Gotchas

- SMTP and Graph `sendMail` have no idempotency key. The tool gateway claims a write by its key before it runs, so a
  retried call does not reach the sender twice; SMTP derives the Message-ID from the key, so a mail sent twice anyway
  carries one id.
- A Graph item's `contentBytes` is base64. The v1 fixtures carry plain text there, which `InboundAttachment.data()`
  refuses; the v1 adapter stores the text as given.

## Tests

`packages/ops_email/tests/` (`make verify` runs them); `services/agents-service/tests/unit/test_mailbox_keys.py` holds
every v1 fixture message's key and references from before the move.
