# Workflows

Status: current.

A workflow is a reviewed typed graph. A developer authors YAML, validates it, stores a draft, publishes a version, and starts a test run. The console can show the same graph. It is not required.

## Lifecycle

```bash
opsai workflows validate workflow.yaml
opsai workflows apply workflow.yaml
opsai workflows publish <id> --note "Ready"
opsai workflows run <id> --input input.json --wait
opsai workflows inspect <run-id>
```

Python:

```python
from ops_ai import OpsAI

ops = OpsAI()
check = ops.workflows.validate("workflow.yaml")
check.raise_for_errors()
draft = ops.workflows.apply("workflow.yaml")
ops.workflows.publish(draft["workflowId"], note="Ready")
run = ops.workflows.run(draft["workflowId"], input={"customerEmail": "ada@example.test"}, wait=True)
```

TypeScript uses the same method names on `ops.workflows` with a parsed object or JSON.

New runs default to `mode="test"`. Live effects need `mode="live"` or `--live`.

## What a definition is

Schema v2 JSON or YAML: `id`, `name`, `nodes[]`, `connections[]`. Each node has `type`, `typeVersion`, `parameters`, and a stable `id`. Connections name those ids and ports.

`GET /v1/workflows/node-types` lists types, ports and parameter schemas. `opsai workflows types` prints the same catalog.

## Debugging

| Failure | Where it appears | What to do |
|---|---|---|
| Invalid graph | `validate` checks, each with `path`, `code`, `message`, `suggestion` | Fix the named node or field |
| Draft not live | 409 `not_live` on a live run | Publish first |
| Step refused | `run.error` and `run.failure.nodeId` | Fix the tool, mapping or input |
| Waiting on a person | `status=waiting` and `taskId` | `opsai workflows decide <task-id> approve` |
| Start schema | 422 on `POST /v1/runs` | Send the request trigger's required fields |

`opsai workflows replay` and `fork` are **Planned**. `opsai workflows retry` retries a stuck run from its last recorded step.

## Examples

Copy a folder from `examples/workflows/`. Pass the folder to the generic commands. The product does not list these folders.

| Folder | Outcome | Status |
|---|---|---|
| `01-normalize-a-request` | Map support fields to a canonical shape | Built |
| `02-route-a-support-message` | Classify a message onto a queue | Built |
| `03-email-customer-enrichment` | Enrich a support email from read tools | Built |
| `04-draft-and-approve-a-reply` | Draft a reply; approve sends, reject or timeout does not | Built |
| `05-reconcile-invoice-and-po` | Merge two records and review disagreement | Built |
| `06-read-a-claim-and-open-a-case` | Extract a claim and open a case | Built |
| `07-calculate-and-approve-a-hold` | Cap, approve and place a hold | Built |
| `08-one-child-per-record` | Trigger child workflows | Built |
| `09-wait-for-verification` | Resume when a verification result arrives | Built |
| `10-schedule-an-sla-follow-up` | Wait until a date, then a human task | Built |
| `11-purge-after-file-deleted` | Purge derived data on `file.deleted` (system, event-started) | Built |
| `12-roles-refuse-a-start` | Same W2 start refused without the cell, then passed with it | Built |
| `13-transform-a-record` | Map one input field onto an output field | Built |
| `14-filter-a-list` | Keep items that match a field predicate | Built |
| `15-retrieve-from-knowledge` | Search the handbook and take found or notFound | Built |
| `16-send-a-message` | Reply on the channel that started the run | Built |
| `17-repeat-until-done` | Loop until a predicate holds, or stop at the cap | Built |
| `18-ask-a-person` | Time out an ask with a zero deadline | Built |
| `19-fire-on-a-clock` | A due tick starts one run | Built |

Node coverage: [workflow-example-coverage.md](workflow-example-coverage.md).

### Example 1 — Normalize a support request

An app posts `customerEmail`, `subject` and `message`. Set fields emits `customer.email`, `title`, `body` and `source`. A missing email fails start validation.

```bash
opsai workflows validate examples/workflows/01-normalize-a-request
opsai workflows apply examples/workflows/01-normalize-a-request
opsai workflows run normalize_support_request --input examples/workflows/01-normalize-a-request/fixtures/valid.json --wait
```

```python
ops.workflows.run(
    "normalize_support_request",
    input={"customerEmail": "ada@example.test", "subject": "Card", "message": "Where is my refund?"},
    wait=True,
)
```

Nodes: `ops.trigger.request` → `ops.data.set` → `ops.flow.end`. No model, tool or person.

### Example 2 — Route an inbound support message

Classify text onto a queue with one `ops.ai.classify` call. Categories are billing, technical and cancellation. Below the 0.6 floor the run leaves by `otherwise` and ends as `other`. A model answer outside the schema ends as `classify_failed`.

```bash
opsai workflows validate examples/workflows/02-route-a-support-message
opsai workflows apply examples/workflows/02-route-a-support-message
opsai workflows run route_support_message --input examples/workflows/02-route-a-support-message/fixtures/billing.json --test --wait
```

```python
ops.workflows.run(
    "route_support_message",
    input={"text": "I was charged twice this month."},
    mode="test",
    wait=True,
)
```

Nodes: `ops.trigger.request` → `ops.ai.classify` → `ops.flow.end`. No tool, write or saved agent.

The first roles lesson reuses this start: [12-roles-refuse-a-start](../../examples/workflows/12-roles-refuse-a-start/). A signed-in person without `workflows.edit` gets `403 role_required`. The same start succeeds for a person who has the cell. People are chosen through `can()`, not a role name.

### Later examples

Examples 2–11 live in the same tree. Each README points here. Example 2 spends one classify call. Example 3 fans an email into extract and a customer search, joins them, and asks a saved agent for a structured recommendation. Example 4 drafts a reply, waits for a person, and expires to `escalated` when the review times out. Example 7 is the hold path, also startable from assistant chat and from `workflow:calculate_account_hold`. Example 11 is the shipped system workflow on `file.deleted`: delete a file; do not start it by hand.

AI nodes declare why they exist, their input, instruction, schema, model alias and fallback port in the folder README and in `evaluation.yaml` when present.

## Start surfaces

Request, hosted form (members-only in the console; a signed public link only when the embed app's origin is set), batch, mailbox, service event, parent workflow, Ops Assistant start card, specialist agent `workflow:<id>`, and a scoped API key are built. Signed webhook, schedule and poll stay **Planned**.
