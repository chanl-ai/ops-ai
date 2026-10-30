# What's built today

Status: current. Each row is read from the code of this release. Built means it runs and is covered by an automated
use case or test; Partial names what runs and what does not; Planned means designed and not in the code.

## Agents and chat

| Capability | Status |
|---|---|
| Chat with an agent: streamed answers, citations, tables and charts in the conversation | Built |
| Tool calls from chat, with a person approving each write and a fresh sign-in for payments | Built |
| Knowledge bases with answers cited by page and section | Built: full-text search; vector search planned |
| Skills: versioned instructions an agent loads when they match, published through review | Built |
| Guardrails: blocked topics with a written scope, checked before and after each answer, failing closed | Partial: blocked topics; other kinds, such as required citations or an output shape, planned |
| Personal data masked in what people see | Built: emails, national ID, card, phone and account numbers; names planned |
| Agent memories, with a retention setting | Built |
| Testing a draft agent on its own page before publishing | Built |
| An agent as a workflow step, and a published workflow as an agent's tool | Built |
| Chat widgets on your other web pages | Partial: widgets are configured, published and keyed in the console; the app that serves them has no image yet |
| Agents that run on a schedule toward a goal and report back, with no chat | Planned |

## Workflows, tasks and cases

| Capability | Status |
|---|---|
| A visual editor over typed steps: triggers, data steps, branches, joins, waits, AI steps, human tasks, tool calls, child workflows, cases | Built: 25 step types |
| AI steps with no saved agent: classify, summarise, extract from text, draft | Built |
| Human tasks from versioned task types: what the person sees and the actions they can take | Built |
| Cases from versioned case types: one record per piece of work, with its tasks, actions and history | Built |
| Deadlines on tasks, waits and reminders | Built on PostgreSQL |
| A child workflow per item, with the parent waiting for all of them | Built |
| Crash safety: every step journaled, a write made once, a dead worker's run taken over | Built |
| Versions pinned per run; publishing through a second person's review | Built |
| Triggers: an API request, a team mailbox, an event from another service | Built |
| Triggers: a schedule, an incoming webhook, polling a system | Planned |
| Code steps | Partial: formulas and transforms in a bounded sandbox; no general code runtime |
| Load figures for many concurrent runs | Planned |

## Channels

| Capability | Status |
|---|---|
| Team mailboxes over IMAP, Gmail or Microsoft 365, with replies over SMTP, Microsoft Graph or a mail API, each message read once | Built |
| A REST API for other systems, with API keys scoped to a team | Built |
| A task API: another system opens a typed human task and reads the decision | Built |
| AI assistants calling the team's tools over MCP | Partial: read tools in the test environment |
| Webhooks to tell another system a run finished or is waiting | Planned: callers poll today |

## Files and documents

| Capability | Status |
|---|---|
| Files: upload, type judged from the bytes, size and type limits, one stored copy per content | Built |
| Storage on a volume, S3 or Azure Blob, chosen per upload purpose | Built |
| Retention classes, a delete-after date, WORM object lock, legal holds | Built |
| Deleting files automatically when their retention ends | Planned |
| Malware scanning | Partial: a hook for your scanner; no scanner ships |
| Document types, versioned, with fields, checks and a score floor | Built |
| Reading a document: layout, OCR for scans, fields with the place on the page each came from | Built |
| A person checking a doubtful read beside the page, and corrections taught back as examples | Built |
| Tables inside documents, splitting one file into several documents, accuracy per field | Planned |

## Data gateway and tools

| Capability | Status |
|---|---|
| Tool modules from OpenAPI 3.0 and 3.1, from an MCP server, or written in the console; versions and a Security review for major changes | Built |
| Connections per test and production: API key, basic, bearer, OAuth client credentials, OAuth authorization code, an app's signed client assertion in place of a secret, a signed service-account grant, client certificate | Built |
| Each person connecting their own account | Planned |
| Approval tokens bound to the exact input, approver counts, step-up, rate and amount limits | Built |
| The outbound allow-list, the encrypted credential store, the call log | Built |
| Check before sending: a model judges a write against the team's sending policy | Built |
| Mock answers for tests, with writes in tests always answered from the mock | Built |

## AI gateway

| Capability | Status |
|---|---|
| Versioned aliases over any OpenAI-compatible endpoint, with prices and clearance | Built |
| Model keys per caller with budgets, tenant shares, rate limits, expiry and rotation | Built |
| A metadata-only call log | Built |
| A data sensitivity gate per alias | Partial: the gate is built; callers do not yet mark each call's level |
| Anthropic's own API, failover between providers, a console page for aliases and keys | Planned |

## Identity, governance and audit

| Capability | Status |
|---|---|
| Single sign-on over OIDC and SAML, chosen by verified email domain; password sign-in; step-up | Built |
| Six built-in roles over a grid of areas and actions, and a page that explains each decision | Built |
| Custom roles | Planned |
| Teams as the data boundary, enforced in every service's store layer | Built |
| Teams enforced in the database as well | In progress |
| Tenants enforced in the database | Partial: agents and platform tables; the other five services planned |
| A publish review for every definition, with a team policy for which publishes need one | Built |
| The audit log and the security audits | Built |
| A tamper-evident audit chain, retention settings and export to WORM storage | Planned |

## Deployment and operations

| Capability | Status |
|---|---|
| PostgreSQL 15 or newer, Azure Database for PostgreSQL | Built |
| Azure SQL and SQL Server | Partial: scripts ready for review; services do not run on it yet ([Azure SQL](azure-sql.md)) |
| Docker Compose on one machine | Built |
| Kubernetes with Kustomize | Built: proven on a local cluster |
| A Helm chart; one VM with no container runtime | Planned |
| Database scripts for your DBA: install, upgrade, downgrade, drift check, one login per service | Built |
| The install script: `git clone` and `./install.sh`, with questions, flags or an answers file; then upgrade (rolled back on a failed check), back up, restore, status, logs and uninstall | Built: proven on one machine; a Linux server and an upgrade across two releases that change the schema are still to be run ([Install](install.md)) |
| Images pulled from `ghcr.io/chanl-ai/ops-ai` for x86-64 and ARM64, or loaded from a release's offline image file, or built from source | Built |
| DBA mode: the install writes the database scripts, waits for your DBA, and checks the schema before it goes on | Built |
| Structured JSON logs, metrics | Planned |
