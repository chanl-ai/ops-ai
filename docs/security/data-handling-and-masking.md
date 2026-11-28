# Data handling and masking

Status: current.

Your agents work on real customer data: card numbers, account numbers, national ID numbers. The people who read a chat, a run or a document's examples afterwards, such as a supervisor reviewing yesterday's conversations, rarely need to see those numbers in full. Ops AI masks them for the people reading, and keeps the real values for the work itself, so the agent can still look up the account.

This page shows you how to see the masking working, what it covers, where your data is stored and how long it is kept.

## See the masking on a real chat

<!-- site: steps -->
1. Open a chat with one of your team's agents and type a message that contains a card number and an email address, for example "Card 4111 1111 1111 1111, contact m.rossi@example.com".
2. Read the agent's answer, its tool calls and any passages it cites. The card number and the email address appear masked.
3. Open a tool call the agent made. It acted on the real values, because masking changes what people see and not what the work receives.

If your agent echoes the number back, the echo is masked too. A number split across two streamed chunks is masked as one number.

## What masking covers

<!-- site: before-after caption="The same message as the agent works on it and as a person reads it" -->
- **What the agent and its tools receive**: The real values.
  - A lookup tool gets the real account number
  - The model sees the real text
- **What people read**: Masked values.
  - Answers, structured output and tool call records
  - Cited passages from your knowledge bases
  - Output of workflow AI steps and document type examples

Masking applies to email addresses, national ID numbers (SSNs), card numbers, phone numbers and account numbers. It also masks a value by the name of its field, so a last-four or a lettered account id under a field named account, card, iban, tax or ssn is masked even though no pattern matches it. A field that only mentions one of those words, such as an account name or a card limit, stays readable. Service logs go through the same masking.

These settings control masking and the features that send data to a model.

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Mask personal data, per agent | Masks what people see of that agent's chats | On | A builder, in the agent's guardrails. Switching it off is a security change, so its publish always waits for a second person's review |
| Mask personal data in AI steps, per team | Masks what people see of workflow AI steps and document type examples | On | A builder or admin of the team, in Govern › Policies |
| AI steps in workflows, per team | Lets the team's workflows use the AI steps Classify, Summarise, Extract from text and Draft | Off | A builder or admin of the team, in Govern › Policies |
| Page images to the model, per team | Lets document types show the model the image of a scanned page | Off | A Security admin, in Govern › Policies |

Which model may receive the real values is decided per model alias, as [Model calls](model-calls.md) explains.

## If you leave masking off

With agent masking off, a supervisor reading a transcript sees every customer's full card and ID numbers, and so does anyone who gets a copy of the transcript. The setting is on by default for that reason, and turning it off is reviewed before it goes live.

## Where your data is stored

| Data | Where it lives | What protects it |
|---|---|---|
| Records: agents, workflows, runs, chats, cases, knowledge text and logs | One PostgreSQL or SQL Server database that you run, or the hosted one | Each service has its own database login that reaches only its own tables, and the database filters rows by organisation and team ([Tenancy and isolation](tenancy-and-isolation.md)) |
| Files | A volume, S3 or an S3-compatible store, or Azure Blob Storage, chosen for each upload purpose by a Security admin | The type is judged from the file's own bytes, size and type limits apply, a file with the same content in the same team is stored once, and storage credentials are stored encrypted |
| Credentials for your systems | Sealed in the database with AES-256-GCM under the installation's secrets key | No API returns them, answers and logs are scrubbed of them, and every use is recorded |
| Model call log | The database | Metadata only: key, model, tokens, cost, time taken and outcome |

Ops AI sends no telemetry. Keep the installation's secrets key with your backups, because stored credentials cannot be read without it.

## How long data is kept

| Data | What happens | Who changes it |
|---|---|---|
| Files | Each upload purpose has a retention class, and a file cannot be deleted before its date. On S3 and Azure Blob, a write-once class sets the store's object lock in compliance mode | A Security admin, in Settings › Storage |
| Legal hold | A held file cannot be deleted by anyone until the hold is lifted, and each hold keeps its history | A person with file management rights |
| Deleting a file | Also removes what was read from it, such as extractions and their corrections | Members who may delete the file |
| Agent memories | Kept until the person removes them. With a retention period set, memories older than that are deleted and each deletion is recorded | A builder or admin, in Govern › Policies |
| Secret use and change records | Deleted after 90 days | Not configurable |
| Sign-ins in progress | Expire after ten minutes | Not configurable |

## Limits today

- Names are not masked, because no pattern finds a name without a model call. Masking names is planned.
- Files are not deleted automatically when their retention date passes. The date only blocks an earlier delete.
- Run journals, events, tool call logs and the audit log are kept with no expiry. A retention setting per organisation and export are planned.
- No malware scanner ships in the package. A new file stays pending and unreadable until your scanner answers, and scanning can be turned off only in development.
- Keeping credential values in your own key vault, and a hardware or cloud key manager for the installation's keys, are planned.

## Next

<!-- site: cards -->
- **[Model calls](model-calls.md)**: Which model receives what, and under which limits.
- **[Access, approvals and audit](access-approvals-and-audit.md)**: The records kept as evidence.
- **[Database](../deploy/database.md)**: Installing, upgrading and checking the database an install runs on.
