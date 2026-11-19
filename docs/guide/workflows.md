# Workflows

Status: current. The commands and folders below are checked by the example tests; what is planned says so.

A workflow is a versioned graph of typed steps that runs the same way every time. You write it as YAML or JSON, check
it, save a draft, publish a version and start a test run, all from the command line or an SDK. The console shows and
edits the same graph, and you do not need it to build one.

## Lifecycle

Every command below reads its address and sign-in from a profile. In an example folder, `setup.py` writes
`.ops-profile.json` and `OPS_CONFIG` names it ([Quickstart](quickstart.md#run-your-first-workflow)); elsewhere the
command reads `~/.config/ops-ai/config.json`. A command that takes a definition also takes an example folder, and
reads its `resources/workflow.yaml`.

| Step | Command | What it does |
|---|---|---|
| Check | `opsai workflows validate workflow.yaml` | Lists every problem, each with its path, code, message and a suggestion |
| Save a draft | `opsai workflows apply workflow.yaml` | Creates or updates the draft |
| Publish | `opsai workflows publish <id> --note "Ready"` | Requests the publish; a second person reviews it unless the team's publish policy says otherwise |
| Run | `opsai workflows run <id> --input input.json --wait` | Starts a test run and waits for it to end; `--live` makes a live run |
| Test from fixtures | `opsai workflows test <folder>` | Runs every fixture case in an example folder |
| Look at a run | `opsai workflows inspect <run-id>`, `opsai workflows trace <run-id>` | The run, and its timeline step by step |
| Decide a task | `opsai workflows decide <task-id> approve` | Answers the human task a run waits on |
| Retry | `opsai workflows retry <run-id>` | Retries a stuck run from its last recorded step |

From Python; TypeScript has the same method names on `ops.workflows`, taking a parsed object or JSON:

```python
from ops_ai import OpsAI

ops = OpsAI()
check = ops.workflows.validate("workflow.yaml")
check.raise_for_errors()
draft = ops.workflows.apply("workflow.yaml")
ops.workflows.publish(draft["workflowId"], note="Ready")
run = ops.workflows.run(draft["workflowId"], input={"customerEmail": "ada@example.test"}, wait=True)
```

> [!NOTE]
> A new run is a test run unless you ask for a live one (`mode="live"`, or `--live`). A test run signs in with the
> App's sandbox account when it has one, and with its live account otherwise
> ([Apps](apps.md#accounts-the-teams-and-your-own)).

Replaying a run, forking it from a step and evaluating a workflow against a dataset (`replay`, `fork`, `eval`) are
planned.

## What a definition holds

A definition has an `id`, a `name`, a list of `nodes` and a list of `connections`. Each node has a `type`, a
`typeVersion`, its `parameters` and a stable `id`; each connection names two node ids and their ports.
`opsai workflows types` prints every step type with its ports and parameter schema, as `GET /v1/workflows/node-types`
does, and [workflow example coverage](workflow-example-coverage.md) names the example that teaches each one.

## When something goes wrong

| What you see | Where | What to do |
|---|---|---|
| The graph is invalid | `validate` lists each problem with `path`, `code`, `message` and `suggestion` | Fix the node or field it names |
| 409 `not_live` | A live run of a workflow with no published version | Publish first |
| 422 on start | The input does not match the request trigger's schema | Send the trigger's required fields |
| A step was refused | `run.error`, and `run.failure.nodeId` names the step | Fix the tool, the mapping or the input |
| `status=waiting` with a `taskId` | The run waits for a person | Decide it in Human Tasks, or `opsai workflows decide <task-id> approve` |

## Examples

Copy a folder from `examples/workflows/` and pass it to the commands above.

| Folder | What it shows | Status |
|---|---|---|
| `01-normalize-a-request` | Map a support request's fields onto one shape | Built |
| `02-route-a-support-message` | Classify a message onto a queue | Built |
| `03-email-customer-enrichment` | Enrich a support email from read tools and ask an agent for a recommendation | Built |
| `04-draft-and-approve-a-reply` | Draft a reply; approving sends it, rejecting or a timeout does not | Built |
| `05-reconcile-invoice-and-po` | Merge two records and send a disagreement to review | Built |
| `06-read-a-claim-and-open-a-case` | Read a claim document and open a case | Built |
| `07-calculate-and-approve-a-hold` | Cap an amount, approve it and place a hold | Built |
| `08-one-child-per-record` | Start one child workflow per record | Built |
| `09-wait-for-verification` | Resume when a verification result arrives | Built |
| `10-schedule-an-sla-follow-up` | Wait until a date, then hand a task to a person | Built |
| `11-purge-after-file-deleted` | Remove derived data when a file is deleted; the platform starts it, never a person | Built |
| `12-roles-refuse-a-start` | A person without permission to edit workflows is refused a start that another person may make | Built |
| `13-transform-a-record` | Map one input field onto an output field | Built |
| `14-filter-a-list` | Keep the items that match a condition | Built |
| `15-retrieve-from-knowledge` | Search a handbook and branch on found or not found | Built |
| `16-send-a-message` | Reply on the channel that started the run | Built |
| `17-repeat-until-done` | Loop until a condition holds, or stop at the limit | Built |
| `18-ask-a-person` | Ask a person, and time out | Built |
| `19-fire-on-a-clock` | Start one run when a due time passes | Built |

### Example 1: normalize a support request

An app posts `customerEmail`, `subject` and `message`; the workflow maps them onto `customer.email`, `title`, `body`
and `source`, and a request without an email is refused at the start. Its steps are `ops.trigger.request`,
`ops.data.set` and `ops.flow.end`, with no model, tool or person. The [Quickstart](quickstart.md#run-your-first-workflow)
runs it.

### Example 2: route a support message

One `ops.ai.classify` step puts a message into billing, technical or cancellation. Below a confidence of 0.6 the run
leaves by `otherwise` and ends as `other`; a model answer outside the schema ends as `classify_failed`.

```bash
uv run python examples/workflows/02-route-a-support-message/setup.py
cd examples/workflows/02-route-a-support-message
OPS_CONFIG=.ops-profile.json uv run opsai workflows apply .
OPS_CONFIG=.ops-profile.json uv run opsai workflows run route_support_message --input fixtures/billing.json --wait
cd ../../..
```

Each AI step's folder README names why the step exists, its input, instruction, answer schema, model alias and the
port it leaves by when the model fails.

## Ways to start a run

| Start | Status |
|---|---|
| An API request, or an API key scoped to the team | Built |
| A hosted form: for team members in the console, or as a signed public link once the embed app's address is set | Built |
| A batch: one run per row of a CSV or JSON file | Built |
| A team mailbox | Built |
| An event from another service | Built |
| A parent workflow | Built |
| The Ops Assistant's start card, or an agent's `workflow:<id>` tool | Built |
| A due time on the platform clock (`ops.trigger.schedule`) | Built |
| A recurring schedule, a signed incoming webhook, polling another system | Planned |
