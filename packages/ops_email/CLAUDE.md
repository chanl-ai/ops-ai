# ops_email: working rules

Status: current.

Email in and out behind two protocols, `MailSource` and `MailSender`, with Microsoft Graph, IMAP, SMTP, Resend and dev
providers picked from settings. It holds no service's rules: a consumer decides what a message starts and what a send
is for. Usage and consumers: [README.md](README.md). Package rules and test commands: [../CLAUDE.md](../CLAUDE.md);
repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `inbound` | `MailSource`, `IdleSource`, `InboundMessage`, `InboundAttachment`, `EmailFilter`, `DeltaPage`, `drain`, `normalise_message_id` |
| `outbound` | `MailSender`, `OutboundMessage`, `OutboundAttachment`, `SmtpSender`, `ResendSender`, `FolderSender` (dev), `MemorySender`, `UnconfiguredSender` |
| `graph` | `GraphMailSource`, `GraphSender`, `GraphToken`: the delta query over a mail folder, `sendMail`, and the app token |
| `imap` | `ImapMailSource`: one folder of one mailbox read by UID, over stdlib `imaplib` in a worker thread |
| `providers` | `EmailProviders`: the install's own sender from `Settings.mail_provider`, built once per process; a missing secret raises at start |
| `testing` | Graph-shaped sources over a list or a folder of JSON files, for tests only |

## Contract with callers

- `drain` returns the next cursor only after the last page is handled, so a consumer saves the cursor only after it
  returns and a poll that dies part-way starts again from the saved one.
- The dedupe key is the normalised Message-ID, or a SHA-256 of sender, time and subject when there is none.
- Every outbound message carries the caller's idempotency key. SMTP and Graph `sendMail` have no idempotency of their
  own: the tool gateway claims a write by its key before it runs, and SMTP derives the Message-ID from the key.
- Mail in is each team's mailbox records, never a setting; only the install's own sender comes from settings.

Depends on `ops_service_kit`. Depended on by agents-service, platform-service and tools-service.

## Run and test

| Task | Command |
|---|---|
| The suite | `make test PKG=packages/ops_email` (`make test` starts GreenMail and Mailpit with `db-up`) |
| One file | `make test PKG=packages/ops_email T=tests/test_imap.py` |
| Lint, format, types | `uv run ruff check packages/ops_email`, `uv run ruff format --check packages/ops_email`, `uv run pyright packages/ops_email` |

The IMAP and SMTP tests skip when GreenMail or Mailpit is not running (`tests/conftest.py:36`). They read the ports from
`OPS_GREENMAIL_*_PORT` and `OPS_MAILPIT_*_PORT`, which `make/env.mk` sets. The Graph provider is tested on a mock
transport only (**unverified** against a tenant); testing against a real mailbox is in
[docs/packages/ops_email/test-with-gmail.md](../../docs/packages/ops_email/test-with-gmail.md).

## Reference docs

- [docs/packages/ops_email/overview.md](../../docs/packages/ops_email/overview.md): providers, settings and gotchas.
  Its consumers table lists `api/channels/mailbox/adapter.py`, which no longer exists
