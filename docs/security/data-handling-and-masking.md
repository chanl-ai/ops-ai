# Data handling and masking

Status: current. Checked against the release's masking, storage and retention code.

Agents and workflows work on real customer data: card numbers, account numbers, national ID numbers. The people
reading a chat or a run usually do not need to see those values in full. This page covers what people see masked by
default, what the model still sees, where data is stored, and how long it is kept.

## Try it

<!-- site: steps -->
1. Open a chat with an agent of your team and paste a message holding a card number and an email address.
2. The agent's answer, its tool calls and its citations show those values masked.
3. The agent still acted on the real values: a tool it called received them as you typed them.

## How masking works

Masking hides values from people, not from the work. The model and the tools receive real values, so an agent can look
up an account; the people reading the chat, the run or a document type's examples see them masked.

| Masked by default | Where |
|---|---|
| Email addresses, national ID numbers, card numbers, phone numbers and account numbers | In an agent's streamed answers, its tool call records and its citations; in the output of workflow AI steps; in the examples a document type learned from corrections |

Two switches control it, both on by default:

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Mask personal data (per agent) | Masks what people see of that agent's chats | On | A builder, in the agent's guardrails; switching it off is a security change, so its publish always waits for a second person's review |
| Mask personal data in AI steps (per team) | Masks what people see of the team's workflow AI steps and document type examples | On | A Security admin, in Governance › Policies |
| AI steps in workflows (per team) | The team's workflows may use AI steps (classify, summarise, extract, draft) | Off | A Security admin, in Governance › Policies |
| Page images to the model (per team) | Document types may show the model the image of a scanned page | Off | A Security admin, in Governance › Policies |

Which model may receive the real values is decided per model: see [Model calls](model-calls.md).

## Where data is stored

| Data | Where it lives | What protects it |
|---|---|---|
| Records (agents, workflows, runs, chats, cases, knowledge text, logs) | One PostgreSQL database you run, or the hosted one | Each service has its own login that reaches only its own tables; organisation and team filters on every read ([Tenancy and isolation](tenancy-and-isolation.md)) |
| Files | A volume, S3 or an S3-compatible store, or Azure Blob Storage, chosen per upload purpose by a Security admin | Type judged from the bytes; size and type limits; one stored copy per content per team; storage credentials encrypted |
| Credentials for your systems | Sealed in the database with AES-256-GCM under the installation's secrets key, bound to the organisation and the credential's name | Never returned by any API, scrubbed from answers and logs, every use audited |
| Model call log | The database | Metadata only: key, model, tokens, cost, time taken, outcome. No prompt or answer text |

Ops AI sends no telemetry. Nothing in the platform calls home.

## Retention

| Data | What happens | Who changes it |
|---|---|---|
| Files | Each upload purpose has a retention class; a file cannot be deleted before its date. On S3 and Azure Blob a write-once class sets the store's object lock in compliance mode | A Security admin, in Settings › Storage |
| Legal hold | A held file cannot be deleted by anyone until the hold is lifted; every hold keeps its history | A person with file management rights |
| Deleting a file | Also deletes what was read from it | |
| Agent memories | Kept until the person removes them, or for the number of days the organisation sets | A Security admin, in Governance › Policies |
| Sign-ins in progress | Expire after ten minutes | |

## Limits

- Names are not masked. Masking names is planned.
- Files are not yet deleted automatically when their retention date passes; the date only blocks an earlier delete.
- Run journals, events, call logs and the audit log are kept with no retention setting; a setting per organisation and
  export are planned. Saved chat state after a run ends is pruned on request, not on a schedule.
- No malware scanner ships in the package. Ops AI holds a new file as pending until your scanner answers, and scanning
  cannot be turned off outside development.
- Keeping credential values in your own key vault, and a hardware or cloud key manager for the installation's keys,
  are planned. Keep the installation's secrets key with your backups: stored credentials cannot be read without it.

## Next

<!-- site: cards -->
- **[Model calls](model-calls.md)**: Which model receives what, and under which limits.
- **[Access, approvals and audit](access-approvals-and-audit.md)**: The records kept as evidence.
- **[Database](../deploy/database.md)**: Installing, upgrading and checking the database an install runs on.
