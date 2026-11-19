# Security

Status: current. Sections marked planned are being written from the architecture pages.

Answers for a security or risk reviewer judging Ops AI for a regulated team: how teams are kept apart, who can sign
in and do what, which writes need a person's approval, what is recorded, how sensitive data is handled, and what
leaves the install. Each page states the behaviour, the default, how an admin changes it, and the limits.

## Topics

<!-- site: cards -->
| Topic | What it answers |
|---|---|
| [Security and governance](guide/security-and-governance.md) | Sign-in and SSO, roles, approvals, the tool gateway, secrets, masking, audit and platform hardening, on one page |
| [Data handling](guide/data-and-database.md) | What is stored, how tenants and teams are kept apart, retention and the audit trail |
| [Model calls](guide/models.md) | Which model calls leave the install, under which keys, budgets and data-sensitivity limits |

## Coming to this tab

| Page | Status |
|---|---|
| Tenancy and isolation | planned |
| Identity and sign-in | planned |
| Approvals and audit | planned |
| Data handling and masking | planned |
| Model calls | planned |
| Outbound calls and egress | planned |

## Next

<!-- site: cards -->
- **[What's built today](guide/whats-built-today.md)**: What is built and what is planned, read from the code of this release.
- **[Security scanning](deploy/security-scanning.md)**: The checks each release passes and how to verify a signed release.
