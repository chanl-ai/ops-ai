# Workflows

Status: current. Rows marked planned are designed and not built.

Some work should run the same way every time and leave a record: open a case for each court order, place a hold only
after a person approves, reply on the channel the request came in on. A workflow is a versioned graph of typed steps
that does that. Each step's input and output is saved as it runs, so a crash or a restart loses nothing and a write is
never made twice. Some steps are AI (an agent, a classification, an extraction); the rest are rules, tool calls and
people deciding.

## Try it

The [Quickstart](quickstart.md#run-your-first-workflow) writes a three-step workflow and runs it. This one adds an AI
step: it puts a support message into billing or technical, and leaves by `otherwise` below a confidence of 0.6. Save it
as `route.yaml`:

```yaml
schemaVersion: 2
id: route_support_message
name: Route an inbound support message
nodes:
- {id: start, type: ops.trigger.request, typeVersion: 1, name: Message,
   parameters: {inputSchema: {type: object, required: [text], properties: {text: {type: string}}}}}
- id: sort
  type: ops.ai.classify
  typeVersion: 1
  name: Classify
  parameters:
    text: $.input.text
    categories:
    - {name: billing, description: "invoices, charges, refunds"}
    - {name: technical, description: "login, outage, app"}
    minConfidence: 0.6
- {id: billing, type: ops.flow.end, typeVersion: 1, name: Billing, parameters: {outcome: billing}}
- {id: technical, type: ops.flow.end, typeVersion: 1, name: Technical, parameters: {outcome: technical}}
- {id: other, type: ops.flow.end, typeVersion: 1, name: Other, parameters: {outcome: other}}
- {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: classify_failed, result: failed}}
connections:
- {from: {node: start, port: payload}, to: {node: sort, port: in}}
- {from: {node: sort, port: billing}, to: {node: billing, port: in}}
- {from: {node: sort, port: technical}, to: {node: technical, port: in}}
- {from: {node: sort, port: otherwise}, to: {node: other, port: in}}
- {from: {node: sort, port: error}, to: {node: failed, port: in}}
```

```bash
opsai workflows validate route.yaml
opsai workflows apply route.yaml
opsai workflows run route_support_message --wait --input '{"text": "I was charged twice this month."}'
```

The run ends with the outcome `billing`. A model answer outside the categories leaves by `error` and ends as
`classify_failed`. `opsai workflows types` lists every step type with its ports and settings.

You do not need the console to build a workflow, but it shows and edits the same graph under **Build › Workflows**.

## Lifecycle

Every command reads its address and sign-in from your profile ([Install the command line](install-cli.md#sign-in)).

| Step | Command | What it does |
|---|---|---|
| Check | `opsai workflows validate workflow.yaml` | Lists every problem, each with its path, code, message and a suggestion |
| Save a draft | `opsai workflows apply workflow.yaml` | Creates or updates the draft |
| Save a working copy | `opsai workflows save-copy <id> workflow.yaml` | Saves it as the workflow's working copy, problems and all, and makes no version; refused with `stale_base` when someone saved since you read it |
| See what changed | `opsai workflows diff <id> --from live --to working-copy` | Each step added, removed, changed (with its settings) or moved |
| Publish | `opsai workflows publish <id> --note "Ready"` | Requests the publish of the newest draft; a second person reviews it unless the team's publish policy says otherwise. With `--working-copy` it makes the next version from the working copy and requests its publish in one call, refused before any version is made while `publish-preview` lists a blocker |
| Run | `opsai workflows run <id> --input input.json --wait` | Starts a test run and waits for it to end; `--live` makes a live run |
| Test from fixtures | `opsai workflows test <folder>` | Runs every fixture case in a folder |
| Look at a run | `opsai workflows inspect <run-id>`, `opsai workflows trace <run-id>` | The run, and its timeline step by step |
| Decide a task | `opsai workflows decide <task-id> approve` | Answers the human task a run waits on |
| Retry | `opsai workflows retry <run-id>` | Retries a stuck run from its last recorded step |
| Redrive | `opsai runs redrive <run-id>`, `opsai runs bulk redrive --code tool_failed` | Runs a Failed or Stuck run again from the step that failed, on the version it started on, once you have fixed the cause. Steps that finished return what they recorded and run nothing; a write is never sent twice. `bulk` redrives or cancels every run of your team that a filter matches (workflow, kind, code, time) |
| Replay, fork, evaluate | `opsai workflows replay`, `fork`, `eval` | Planned |

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
> app's sandbox account when it has one, and with its live account otherwise
> ([Tools and apps](apps.md#accounts-the-teams-and-your-own)).

A run keeps the version it started on. Publishing a new version changes only the runs that start after it.

## What a definition holds

A definition has an `id`, a `name`, a list of `nodes` and a list of `connections`. Each node has a `type`, a
`typeVersion`, its `parameters` and a stable `id`; each connection joins one node's output port to another's input.
`opsai workflows types` prints every step type with its ports and parameter schema.

## When something goes wrong

| What you see | Where | What to do |
|---|---|---|
| The graph is invalid | `validate` lists each problem with `path`, `code`, `message` and `suggestion` | Fix the node or field it names |
| 409 `not_live` | A live run of a workflow with no published version | Publish first |
| 422 on start | The input does not match the request trigger's schema | Send the trigger's required fields |
| A step was refused | `run.error`, and `run.failure.nodeId` names the step | Fix the tool, the mapping or the input |
| `status=waiting` with a `taskId` | The run waits for a person | Decide it in Human Tasks, or `opsai workflows decide <task-id> approve` |

## Ways to start a run

| Start | Status |
|---|---|
| An API request, or an API key scoped to the team | Built |
| A hosted form: for team members in the console, or as a signed public link | Built |
| A batch: one run per row of a CSV or JSON file | Built |
| A team mailbox | Built |
| An event from another service | Built |
| A parent workflow | Built |
| A chat, from the assistant's start card or an agent that has the workflow as a tool | Built |
| A due time on the platform clock; the same key runs once | Built |
| A recurring schedule, a signed incoming webhook, polling another system | Planned |

## Next

<!-- site: cards -->
- **[Build with Ops AI](build-with-ops-ai.md)**: nineteen example workflows, from mapping one field to a child workflow per record.
- **[Workflow examples](examples/workflows.md)**: check, publish, run, decide and fix a workflow in Python, TypeScript and the command line.
- **[Human tasks and approvals](human-tasks.md)**: pause a run for a person.
- **[Cases](cases.md)**: open a case from a run.
- **[Agents](agents.md)**: add an agent step, or give a workflow to an agent as a tool.
