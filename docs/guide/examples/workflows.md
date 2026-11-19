# Workflow examples

Status: current.

A workflow is a fixed set of steps: the same input takes the same path every time. You write it as a file, check it,
publish it and start runs. These examples build one refund workflow that branches on an amount, waits for a person's
decision, and then asks an agent a question from a step.

Connect first: see [Before you start](README.md#before-you-start).

## What each surface can do

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| Check, save and publish a workflow | built | built, from JSON | built |
| Start a run and wait for it | built | built | built |
| Decide a waiting task | built | built | built |
| Read what a run did | built | built | built |
| Replay or fork a past run | upcoming | upcoming | upcoming |

## Check, publish and run a workflow

**The problem.** Refund requests should follow one rule: a small refund goes through, a large one waits for a person.
You want that rule written down, checked before it is used, and run the same way every time.

**When to use it.** Use a workflow when the steps are known in advance and a reviewer must be able to read them. Use
an agent when the steps depend on the conversation.

The workflow is a list of steps (`nodes`) and the lines between them (`connections`). Each connection leaves a step
by a named port, such as `true` and `false` on a branch.

```yaml title="refund.yaml"
schemaVersion: 2
id: refund_request
name: Refund request
nodes:
- id: start
  type: ops.trigger.request
  typeVersion: 1
  name: Refund request
  parameters:
    inputSchema:
      type: object
      required: [orderId, amount]
      properties:
        orderId: {type: string}
        amount: {type: number}
        reason: {type: string}
- id: large
  type: ops.flow.if
  typeVersion: 1
  name: Over 50?
  parameters:
    conditions:
    - left: $.input.amount
      op: gt
      right: 50
- id: review
  type: ops.flow.humanReview
  typeVersion: 1
  name: Approve the refund
  parameters:
    title: Refund this order?
    summary:
      order: $.input.orderId
      amount: $.input.amount
      reason: $.input.reason
- id: approved
  type: ops.flow.end
  typeVersion: 1
  name: Approved
  parameters:
    outcome: approved
- id: declined
  type: ops.flow.end
  typeVersion: 1
  name: Declined
  parameters:
    outcome: declined
- id: small
  type: ops.flow.end
  typeVersion: 1
  name: Approved without review
  parameters:
    outcome: auto_approved
connections:
- {from: {node: start, port: payload}, to: {node: large, port: in}}
- {from: {node: large, port: "true"}, to: {node: review, port: in}}
- {from: {node: large, port: "false"}, to: {node: small, port: in}}
- {from: {node: review, port: approve}, to: {node: approved, port: in}}
- {from: {node: review, port: reject}, to: {node: declined, port: in}}
```

```python
from ops_ai import OpsAI

ops = OpsAI()

check = ops.workflows.validate("refund.yaml")
check.raise_for_errors()

draft = ops.workflows.apply("refund.yaml")
ops.workflows.publish(draft["workflowId"], note="First version")

run = ops.workflows.run("refund_request", input={"orderId": "1182", "amount": 20}, wait=True)
print(run["status"], run["outcome"])
```

The command line reads the same file, and converts it to JSON for TypeScript.

```bash
opsai workflows validate refund.yaml
opsai workflows apply refund.yaml
opsai workflows publish refund_request --note "First version"
opsai workflows run refund_request --input '{"orderId": "1182", "amount": 20}' --wait
opsai workflows convert refund.yaml --to json -o refund.json
```

TypeScript takes the workflow as an object or as JSON text.

```ts
import { readFileSync } from 'node:fs';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();
const definition = readFileSync('refund.json', 'utf8');

const check = await ops.workflows.validate(definition);
check.raiseForErrors();

const draft = await ops.workflows.apply(definition);
await ops.workflows.publish(draft.workflowId, 'First version');

let run = await ops.workflows.run('refund_request', { input: { orderId: '1182', amount: 20 }, wait: true });
console.log(run.status, run.outcome);
```

| Option of a run | What it does |
|---|---|
| `input` | The values the first step asks for. A run that leaves out a required one is refused. On the command line, give JSON when a value is a number: `key=value` pairs are sent as text |
| `mode` | `test` is the default. `live` (`--live`) lets steps reach real systems, and needs a published workflow |
| `wait` | Return when the run ends or stops at a task for a person. Left out, the call returns as soon as the run starts |

The three surfaces do the same job, so run one of them. `apply` on an unchanged file changes nothing, and publishing a
version that is already live is refused with `not_a_draft`. On a changed file it saves the next draft, and runs keep using the
published version until you publish again. `opsai workflows types` lists every step type with its ports and
parameters.

## Wait for a person and decide

**The problem.** A large refund needs a person's yes. The run should stop, show that person the facts, and carry on
down the path they choose.

**When to use it.** Use a review step before anything a person must answer for. The person who started the run
cannot decide its review, so the examples decide as a second person.

```python
run = ops.workflows.run(
    "refund_request",
    input={"orderId": "1183", "amount": 120, "reason": "Arrived damaged"},
    wait=True,
)
print(run["status"], run["taskId"])

reviewer = OpsAI(profile="reviewer")
reviewer.tasks.decide(run["taskId"], "approve", reason="The photo shows the damage.")

run = ops.runs.wait(run["id"])
print(run["status"], run["outcome"])
```

```ts
run = await ops.workflows.run('refund_request', {
  input: { orderId: '1183', amount: 120, reason: 'Arrived damaged' },
  wait: true,
});
console.log(run.status, run.taskId);

const reviewer = new OpsAI({ profile: 'reviewer' });
await reviewer.tasks.decide(run.taskId, 'approve', { reason: 'The photo shows the damage.' });

run = await ops.runs.wait(run.id);
console.log(run.status, run.outcome);
```

```bash
RUN=$(opsai workflows --json run refund_request --input '{"orderId": "1183", "amount": 120}' --wait | jq -r .id)
opsai tasks decide "$RUN" approve --reason "The photo shows the damage." --profile reviewer
opsai runs show "$RUN"
```

The run carries on in the background after the decision, so `opsai runs show` may print `queued` for a moment. A run that stops at a review has the status `waiting` and names the task. The decision is one of the actions the task
offers, here `approve` or `reject`, and the run leaves the review step by the port with that name. The reviewer signs
in under their own saved profile.

## Ask an agent from a step

**The problem.** One step needs judgement, such as answering a customer's question, and the rest of the workflow
should stay fixed.

**When to use it.** Use an agent step when a published agent already does the job. The workflow gets the agent's
final answer, and takes the `error` port if the agent fails.

```yaml title="returns-answer.yaml"
schemaVersion: 2
id: returns_answer
name: Answer a returns question
nodes:
- id: start
  type: ops.trigger.request
  typeVersion: 1
  name: Question
  parameters:
    inputSchema:
      type: object
      required: [question]
      properties:
        question: {type: string}
- id: ask
  type: ops.ai.agent
  typeVersion: 1
  name: Ask the returns helper
  parameters:
    agent: AGENT_ID
    prompt: $.input.question
- id: answered
  type: ops.flow.end
  typeVersion: 1
  name: Answered
  parameters:
    outcome: answered
    output: $.nodes.ask.out
- id: failed
  type: ops.flow.end
  typeVersion: 1
  name: Failed
  parameters:
    outcome: agent_failed
    result: failed
connections:
- {from: {node: start, port: payload}, to: {node: ask, port: in}}
- {from: {node: ask, port: ok}, to: {node: answered, port: in}}
- {from: {node: ask, port: error}, to: {node: failed, port: in}}
```

The step names the agent by its id, so each surface puts the id in before it saves the workflow.

```python
import yaml

agent = next(a for a in ops.agents.list(search="Returns helper") if a["name"] == "Returns helper")
definition = yaml.safe_load(open("returns-answer.yaml"))
definition["nodes"][1]["parameters"]["agent"] = agent["id"]

ops.workflows.apply(definition)
ops.workflows.publish("returns_answer", note="First version")

run = ops.workflows.run("returns_answer", input={"question": "Can I return a gift?"}, wait=True)
print(run["status"], run["outcome"])
```

```bash
AGENT=$(opsai agents --json list --search "Returns helper" | jq -r '.[0].id')
sed -i.bak "s/AGENT_ID/$AGENT/" returns-answer.yaml

opsai workflows apply returns-answer.yaml
opsai workflows publish returns_answer --note "First version"
opsai workflows run returns_answer --input "question=Can I return a gift?" --wait
opsai workflows convert returns-answer.yaml --to json -o returns-answer.json
```

```ts
const answer = readFileSync('returns-answer.json', 'utf8');
await ops.workflows.apply(answer);
await ops.workflows.publish('returns_answer', 'First version');

run = await ops.workflows.run('returns_answer', { input: { question: 'Can I return a gift?' }, wait: true });
console.log(run.status, run.outcome);
```

The agent must be published, here the one from [Agent examples](agents.md#create-and-publish-an-agent). It works
the other way too: an agent that is granted `workflow:<id>` as a tool can start a published workflow from a chat.

## Read what a run did

**The problem.** A run ended with an outcome you did not expect, and you need to see which path it took.

**When to use it.** Use it after any run. The trace lists each step the run reached, how it ended and the port it
left by.

```python
traced = ops.workflows.trace(run["id"])
for step in traced["steps"]:
    print(step["nodeId"], step["status"], step["port"])
print(traced["failure"])
```

```ts
const traced = await ops.workflows.trace(run.id);
for (const step of traced.steps) console.log(step.nodeId, step.status, step.port);
console.log(traced.failure);
```

```bash
opsai workflows trace "$RUN"
opsai workflows inspect "$RUN"
```

## Fix a refused workflow or run

**The problem.** A file with a mistake, or a run with a missing value, should fail with a message that says what to
change.

**When to use it.** Check a file before you save it, and catch a refused start in code that takes input from
elsewhere.

```python
from ops_ai import BadRequest

broken = ops.workflows.validate({
    "schemaVersion": 2,
    "id": "broken_example",
    "name": "Broken example",
    "nodes": [{"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Start", "parameters": {}}],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "nowhere", "port": "in"}}],
})
for problem in broken.errors:
    print(problem["code"], problem["message"], problem["suggestion"])

try:
    ops.workflows.run("refund_request", input={"orderId": "1184"}, wait=True)
except BadRequest as refused:
    print(refused.status, refused.code, refused.message)
```

| What went wrong | What you see | What to do |
|---|---|---|
| The file breaks a rule | `validate` lists each problem with a code, a message and a suggestion | Fix the step or connection it names |
| A required input is missing | The start is refused with `invalid_input` | Send every field the first step requires |
| You decide your own run's review | The decision is refused with `own_request` | Have another person decide |
| You publish a version that is already live | The request is refused with `not_a_draft` | Nothing to do: that version is the one running |
| A live run of an unpublished workflow | The start is refused with `not_live` | Publish first, or run in test mode |

## Next steps

- [Workflows](../workflows.md): the lifecycle, start surfaces and the full list of example folders.
- [Workflow example coverage](../workflow-example-coverage.md): every step type and the example that teaches it.
- [Agent examples](agents.md): build the agent a workflow step asks.
- [Step-by-step skills](step-by-step-skills.md): numbered steps inside a chat. Upcoming.
