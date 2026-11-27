# Workflow examples

Status: current.

A refund request for $20 and one for $120 should not follow the same path. The small one goes through, and the large
one needs a person's decision. If that rule lives in someone's head or in an agent's instructions, nobody can show a
reviewer where it is written, and it can change without anyone noticing.

A workflow writes the rule down as a fixed set of steps, so the same input takes the same path every time. Without one,
you cannot prove that a large refund was ever checked by a person. These examples build one refund workflow that
branches on an amount, waits for a person's decision, and asks an agent a question from a step.

## The plan

<!-- site: steps -->
1. **Write the workflow as a file** and check it before you save it.
2. **Publish it and start a run**, in test mode first.
3. **Let a second person decide** the large refund, so the run carries on down the path they choose.
4. **Ask an agent** from one step when the work needs judgement.
5. **Read the trace** of any run to see the path it took.

Connect first: see [Connect once, then copy any example](README.md#connect-once-then-copy-any-example).

## What each surface can do

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| Check, save and publish a workflow | built | built, from JSON | built |
| Start a run and wait for it | built | built | built |
| Decide a waiting task | built | built | built |
| Read what a run did | built | built | built |
| Replay or fork a past run | upcoming | upcoming | upcoming |

## Write the refund rule and run it

Every refund request should follow one rule: a small refund goes through, and a large one waits for a person. A
workflow lets you write that rule down, check it before it is used, and run it the same way every time.

Choose a workflow when the steps are known in advance and a reviewer must be able to read them. Choose an agent when
the steps depend on the conversation.

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

The three surfaces do the same job, so you only need to run one of them. Running `apply` on an unchanged file changes
nothing, and publishing a version that is already live is refused with `not_a_draft`. Running `apply` on a changed
file saves the next draft, and runs keep using the published version until you publish again. To see every step type
with its ports and parameters, run `opsai workflows types`.

## Hold a large refund for a person's decision

A large refund needs a person's approval. The run should stop, show that person the facts, and carry on down the path
they choose.

Put a review step before anything a person must answer for. The person who started a run cannot decide its review, so
the examples decide as a second person.

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
OUT=$(opsai workflows --json run refund_request --input '{"orderId": "1183", "amount": 120}' --wait)
RUN=$(jq -r .id <<<"$OUT")
TASK=$(jq -r .taskId <<<"$OUT")
opsai tasks decide "$TASK" approve --reason "The photo shows the damage." --profile reviewer
opsai runs show "$RUN"
```

<!-- site: sequence caption="A large refund stops at a review, waits for a second person and carries on by the port they choose" -->
1. **You → Workflow run**: Start the refund
2. **Workflow run → Human task**: Stops at the review with the status `waiting` and names the task
3. **Reviewer → Human task**: Decides with one of the task's actions, here `approve` or `reject`
   - The reviewer signs in under their own saved profile.
4. **Human task → Workflow run**: The run leaves the review step by the port with that name
5. **Workflow run → You**: Carries on in the background, so `opsai runs show` may print `queued` for a moment

## Let an agent answer one step

When one step needs judgement, such as answering a customer's question, the rest of the workflow can stay fixed. If a
published agent already does the job, use an agent step. The workflow gets the agent's final answer, and takes the
`error` port if the agent fails.

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

The agent must be published, here the one from [Agent examples](agents.md#put-an-agent-your-team-can-chat-with-into-a-file). The
link works in the other direction too. An agent that is granted `workflow:<id>` as a tool can start a published
workflow from a chat.

## See which path a run took

When a run ends with an outcome you did not expect, read its trace to see which path it took. You can trace any run.
The trace lists each step the run reached, how the step ended and the port it left by.

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

## Understand why a file or a run was refused

A file with a mistake, or a run with a missing value, fails with a message that says what to change. Check each file
before you save it, and catch a refused start in any code that takes its input from elsewhere.

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

## What success looks like

The $20 refund ends as `auto_approved`. The $120 refund stops with the status `waiting` and a task, and ends as
`approved` after a second person decides it. The trace of each run lists the steps it reached and the port it left by.

## What to do next

- [Workflows](../workflows.md): the lifecycle, start surfaces and the full list of example folders.
- [Workflow example coverage](../workflow-example-coverage.md): every step type and the example that teaches it.
- [Agent examples](agents.md): build the agent a workflow step asks.
- [Step-by-step skills](step-by-step-skills.md): numbered steps inside a chat. Upcoming.
