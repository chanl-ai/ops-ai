# ops_email

Email in and out for every service, behind two protocols: `MailSource` (a delta of new mail in one folder of one
mailbox, parsed to `InboundMessage`) and `MailSender` (`send(OutboundMessage) -> reference`). `EmailProviders` picks
the provider from settings, so a deployment changes provider by changing settings and secrets, never code.

| Direction | Setting | Providers |
|---|---|---|
| In | none | A team's own mailboxes are records read by their provider (Graph, IMAP; a dev stack's GreenMail); tests read JSON files through `ops_email.testing` |
| Out | `OPS_MAIL_PROVIDER`, `OPS_MAIL_FROM` | `smtp` (`OPS_SMTP_*`), `resend` (`OPS_RESEND_API_KEY`), `graph` (`sendMail`), `fake` (dev: JSON files under `OPS_MAIL_FAKE_OUT_DIR`) |

```python
from ops_email import EmailProviders, OutboundMessage, drain

mail = EmailProviders.from_settings(Settings())
source = mail.source("intake@bank.example", "inbox")
cursor, pages = await drain(source, saved_cursor, handle)  # save cursor only after this returns
await mail.sender().send(OutboundMessage(key, ("customer@example.com",), "Subject", "Body"))
```

Consumers: the email trigger (`services/agents-service/src/ops_agents/api/email_trigger.py`), the mailbox gateway
(`api/mailbox_gateway.py`), platform-service's password mail (`ops_platform/passwords.py`) and tools-service's
`send_reply` tool and mailboxes (`services/tools-service/src/ops_tools/tools.py`, `mailboxes.py`).
Tests: `make test PKG=packages/ops_email`. Docs: [docs/packages/ops_email/overview.md](../../docs/packages/ops_email/overview.md).
The Graph provider is tested on a mock transport only (unverified against a tenant).
