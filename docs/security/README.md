# Security

Status: current. Each page is checked against the code of this release.

Answers for a security or risk reviewer judging Ops AI for a regulated team. Each page states the behaviour, the
default, how an admin changes it, and the limits, and holds for a self-hosted install and a hosted one alike unless it
says otherwise.

## In short

- Every team's data is closed to every other team; an organisation's data is closed to every other organisation.
- People sign in through your identity provider over OIDC or SAML; a first sign-in never makes anyone an admin.
- Software drafts changes; a team decides which writes wait for a person, and every write over MCP does.
- People see personal data masked by default; the model sees real values, and only models cleared for the data serve.
- Every model call goes through one AI gateway in the install, with a key, a budget and no prompt text in its log.
- Tools reach only HTTPS hosts a Security admin allows; agents hold no credentials.
- Nothing in the platform calls home.

## Topics

<!-- site: cards -->
| Topic | What it answers |
|---|---|
| [Tenancy and isolation](tenancy-and-isolation.md) | How teams and organisations are kept apart, in the services and in the database |
| [Identity and sign-in](identity-and-sign-in.md) | OIDC and SAML single sign-on, group rules, passwords, sessions and step-up |
| [Access, approvals and audit](access-approvals-and-audit.md) | Roles, which writes wait for a person, and what is recorded |
| [Data handling and masking](data-handling-and-masking.md) | What people see masked, where data is stored and how long it is kept |
| [Model calls](model-calls.md) | Which model sees what, under which key, budget and clearance |
| [Egress and connections](egress-and-connections.md) | Where a tool call may go, and how it signs in to your systems |

## Next

<!-- site: cards -->
- **[What's built today](../guide/whats-built-today.md)**: What is built and what is planned in this release.
- **[Security scanning](../deploy/security-scanning.md)**: The checks each release passes and how to verify a signed release.
