# Step-by-step skills

Status: current.

Some procedures must happen in order, every time. An agent looks up the charge, confirms the amount with the person,
and only then refunds. If you write that order as free text in a skill, the agent reads it as guidance and may skip a
step. If you write it as a workflow, the order holds, but the conversation with the person is lost.

A step-by-step skill keeps both. The agent works on one step at a time in the chat, a check decides whether the step
is done before the next one starts, and the skill ends with a named exit that a reviewer can read afterwards. Without
it, a team that needs a fixed order has to choose between an agent that may skip a step and a workflow with no chat.

## The plan

<!-- site: steps -->
1. **Write the steps**, each with what the agent does, the check that must hold, and what happens when it does not.
2. **Name the exits**, so every run ends in a state a reviewer can read.
3. **Give the skill to an agent** and follow the steps in a chat.
4. **Read the record** of which step ran, which check passed and which exit ended the skill.

## Which to use

<!-- site: decision caption="Choosing between a skill with instructions only, a step-by-step skill and a workflow" -->
- **Is a person in the conversation?**
  - **No, or the work must survive long waits and restarts**: Use a workflow.
  - **Yes**: The next question is about order.
    - **Must the actions happen in order, with some checked before the next one starts?**
      - **Yes**: Use a step-by-step skill.
      - **No, the agent only needs guidance**: Use a skill with instructions only.

## Write a skill with steps

A skill file gains five fields: `steps`, `exit`, `returns`, `success` and `notWhen`. This example adds a note to a
customer's record in three steps: look the customer up, confirm the wording, save the note. It uses two tools from the
sample team, and its second step runs another skill.

```yaml title="confirm-the-wording.yaml"
name: Confirm the wording
useWhen: A note must be confirmed before it is saved.
instructions: ""
steps:
  - do: Read the note back and ask the person to confirm it.
    check: {text: The person confirmed the wording.}
```

```yaml title="add-a-customer-note.yaml"
name: Add a customer note
useWhen: Staff ask to add a note to a customer's record.
notWhen: Staff only ask to read notes.
instructions: Never add a note to more than one customer.
inputs:
  - name: customer_email
    description: The customer's email
    required: true
steps:
  - do: Look up the customer with @tool:search_customers.
    use: {kind: tool, id: search_customers}
    check: {text: "len(result) == 1"}
    ifNot: {action: exit, exit: not_found}
  - do: Confirm the wording.
    use: {kind: skill, id: CONFIRM_SKILL_ID}
  - do: Add the note.
    use: {kind: tool, id: add_customer_note}
exit:
  not_found: No single customer matches the email.
returns:
  - name: noted
    type: yes_no
    description: Whether the note was added
success:
  - The person confirmed the wording before the note was saved.
```

A step names another skill by its id, so each surface publishes the first skill and puts its id into the second.

```python
import yaml
from ops_ai import OpsAI

ops = OpsAI()

confirm = ops.skills.create(yaml.safe_load(open("confirm-the-wording.yaml")))
ops.skills.publish(confirm["id"], note="First version")

definition = yaml.safe_load(open("add-a-customer-note.yaml"))
definition["steps"][1]["use"]["id"] = confirm["id"]
skill = ops.skills.create(definition)
published = ops.skills.publish(skill["id"], note="First version")

for step in ops.skills.get(skill["id"])["content"]["steps"]:
    print(step["do"], (step.get("check") or {}).get("by"))
```

```ts
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const confirm = await ops.skills.create(parse(readFileSync('confirm-the-wording.yaml', 'utf8')));
await ops.skills.publish(confirm.id, 'First version');

const definition = parse(readFileSync('add-a-customer-note.yaml', 'utf8'));
definition.steps[1].use.id = confirm.id;
const skill = await ops.skills.create(definition);
await ops.skills.publish(skill.id, 'First version');

for (const step of (await ops.skills.get(skill.id)).content.steps) console.log(step.do, step.check?.by);
```

```bash
CONFIRM=$(opsai skills apply confirm-the-wording.yaml --json | jq -r .id)
opsai skills publish "$CONFIRM" --note "First version"

sed -i.bak "s/CONFIRM_SKILL_ID/$CONFIRM/" add-a-customer-note.yaml
SKILL=$(opsai skills apply add-a-customer-note.yaml --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"
```

`create` needs `instructions`, but a skill with steps may leave them empty. `opsai skills apply` creates the skill, or
saves a new draft of the skill the file names by id, slug or name. The stored steps say who judges each check, either
`rule` or `model`.

A skill can also be written as plain text, without the file fields. [Write the skill as text](#write-the-skill-as-text)
at the end of this page lists what each kind of line becomes.

## Give the skill to an agent and follow the steps

The agent needs the skill, the tools its steps use and the skill its second step runs, and granting each one by hand
invites mistakes. `add_reference` grants an agent a skill, a tool, a knowledge base, another agent or a workflow by
its kind and id. When you grant a skill this way, it brings the tools and knowledge bases it names and the skills its
steps run.

```python
agent = ops.agents.apply({
    "name": "Notes desk",
    "role": "Adds notes to customer records",
    "instructions": "Help branch staff add notes to customer records. Keep answers short.",
})
added = ops.agents.add_reference(agent["id"], "skill", skill["id"])
for item in added["added"]:
    print(item["kind"], item["id"])

ops.agents.publish(agent["id"], note="First version")

thread = ops.chat.start(agent["id"], test=True)
events = list(ops.chat.say(
    thread["id"],
    "Add a note: prefers email.",
    skill=skill["id"],
    inputs={"customer_email": "ada@example.test"},
))
running = events[-1]["message"]["skillRun"]["running"]
print(running["name"], running["step"], running["stepsTotal"], running["stepText"])
```

```ts
const agent = await ops.agents.apply({
  name: 'Notes desk',
  role: 'Adds notes to customer records',
  instructions: 'Help branch staff add notes to customer records. Keep answers short.',
});
const added = await ops.agents.addReference(agent.id, 'skill', skill.id);
for (const item of added.added) console.log(item.kind, item.id);

await ops.agents.publish(agent.id, 'First version');

const thread = await ops.chat.start(agent.id, { test: true });
const events = await ops.chat.say(thread.id, 'Add a note: prefers email.', {
  skill: skill.id,
  inputs: { customer_email: 'ada@example.test' },
});
const running = events.at(-1).message.skillRun.running;
console.log(running.name, running.step, running.stepsTotal, running.stepText);
```

```bash
cat > notes-desk.yaml <<EOF
name: Notes desk
role: Adds notes to customer records
instructions: Help branch staff add notes to customer records. Keep answers short.
EOF
AGENT=$(opsai agents apply notes-desk.yaml --json | jq -r .id)
opsai agents add-reference "$AGENT" skill "$SKILL"
opsai agents publish "$AGENT" --note "First version"

opsai chat say --agent "$AGENT" --test --skill "$SKILL" --input customer_email=ada@example.test -m "Add a note: prefers email."
```

The examples chat with the agent's newest version (`test`), so they do not wait for the publish request to be
approved. Each reply carries the skill's record as `skillRun`. The record holds the skill that is running, the step
it is on, each step's result so far, and the skills that ended. The next reply in the same conversation goes on from that step,
even when the person asks about something else in between. In the reply's `skills` list, `how` is `started` for a
skill that runs step by step.

A skill starts at step 1 however it is started: a person picks it for a reply, as above, or the agent decides the
request matches its use-when line and calls `load_skill` or `switch_skill`.

| Field | What it does |
|---|---|
| `steps` | Up to 30 steps, run in order |
| `steps[].do` | What the agent does in this step |
| `steps[].use` | The one thing the step runs: a tool, another skill, an agent or a workflow. A knowledge base is named in the step's text instead |
| `steps[].check` | What must hold before the step is done |
| `steps[].ifNot` | What happens when the check fails: `retry` (up to 3 times), `goto` another step, or `exit` with a named exit |
| `exit` | The skill's own exits and what each means. Every skill also has `done` and `failed` |
| `returns` | Values the skill hands back when it ends: text, a number, or yes or no |
| `success` | Lines that say what a good run looks like |
| `notWhen` | When the skill should not be used |

In any text of the skill you can name a tool, a knowledge base, a skill, an agent or a workflow with `@`, for example
`@tool:search_customers`. Saving the skill adds what its steps name to the skill's tools and knowledge bases.
`opsai skills references <id> --search note` lists what a step may name.

## Rule checks

A check is either a rule or a sentence. A rule is worked out by code from the step's result, so the model cannot
talk its way past it. A sentence is judged by the model.

```yaml
check: {text: "result.amount <= 500 and result.status == 'settled'"}   # a rule
check: {text: The person confirmed the wording.}                       # a sentence
```

| A rule can use | Examples |
|---|---|
| The step's result and the skill's inputs | `result.amount`, `result.items[0].id`, `inputs.customer_email` |
| Values | Numbers, text in quotes, `true`, `false`, `null`, lists |
| Comparisons | `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `is true`, `is null` |
| Logic and arithmetic | `and`, `or`, `not`, and arithmetic on numbers |
| Functions | `len`, `lower`, `contains`, `exists` |

A missing field reads as `null`, and a comparison with `null` is false. A rule reads only its own step's result and
the inputs. It cannot see the results of earlier steps. Whether a check is a rule or a sentence is decided when the
skill is saved. A text that reads like a rule and is not a valid one is refused, so a typing mistake cannot turn a
rule into a sentence.

## Exits

A skill ends with one exit. `done` is accepted only after the last step has passed. `failed`, or an exit the skill
lists, can end it at any step. A step sends the skill to an exit when its check fails:

```yaml
ifNot: {action: exit, exit: not_found}
```

The caller gets back the exit and the values in `returns`. The caller is the agent, or the step of another skill that
ran this one.

## How the agent moves through the steps

The agent that holds a step-by-step skill starts it and moves through it with four built-in tools.

| Tool | What it does |
|---|---|
| `load_skill` | Starts a skill by its slug at its first step. This is the tool the agent already uses to load a skill without steps, so a skill with steps is never loaded as text |
| `switch_skill` | Starts a skill by its slug, with its inputs. A skill that is already running ends first, so one skill runs at a time. A skill with a required input that is missing does not start, and the agent asks the person for it |
| `step_done` | Says the current step is done. It is refused while the step's tool has not run, and for a step whose rule is checked on the tool's result |
| `exit` | Ends the running skill with one of its exits and its results |

A person can also start the skill by picking it for a reply, as in
[Give the skill to an agent and follow the steps](#give-the-skill-to-an-agent-and-follow-the-steps). While a step names a tool, that tool and knowledge
search are the only systems the agent is offered, so a later step's tool cannot run early. A conversation finishes a
skill on the version it started with, even when a newer version is published meanwhile.

## Approvals

A step's tool waits for approval the same way any tool does. When the tool needs a person's approval, the reply
pauses until they decide. Steps add two rules of their own.

| What happens | What the skill does |
|---|---|
| A person denies the step's call | The skill ends as `failed` at once |
| A step's check fails, or its call is denied | The tools of the later steps are held. No other skill, and no call outside a skill, may use them in that conversation until this skill passes that step |

The hold is per tool. A note held for one customer is held for every customer in that conversation. A reply that
pauses for an approval keeps the step it is on, and goes on from that step after the decision.

## Sub-skills

A step can run another skill, as step 2 of the example does. Use it for a procedure several skills share, such as
confirming a caller. A rule on the step can read how the sub-skill ended:

```yaml
- do: Verify the caller.
  use: {kind: skill, id: sk_verify_caller}
  check: {text: "result.exit == 'done' and result.verified is true"}
  ifNot: {action: exit, exit: failed}
```

| Rule | Detail |
|---|---|
| One level | A skill that a step runs cannot run a skill of its own |
| Inputs | The sub-skill gets the inputs it declares, from the running skill's inputs and then from the result of the step before. A required one that is missing fails the step |
| Passing | The step passes when the sub-skill ends as `done`. A rule on the step can accept other exits: `result.exit in ['done', 'skip']` |
| Results | The rule reads the sub-skill's exit as `result.exit`. It reads the sub-skill's returned values only when the sub-skill ended as `done` |

## What stops a save or a publish

| Problem | When it is refused |
|---|---|
| Results, exits or success lines with no steps | On save |
| Steps in a skill that also has parts, or that loads in every reply | On save |
| A step that tries to run a knowledge base | On save |
| A check that reads like a rule and is not a valid one | On save |
| `goto` a step that does not exist, or an exit the skill does not list | On save |
| A step that runs its own skill, or a skill whose steps run a skill | On save |
| A step that names a tool your team no longer offers | On publish. The error names each problem and the step it is on |
| A skill written as text mentions something that no longer exists, or makes more than 30 steps | On publish only; the draft saves. The error names the line |
| A skill written as text runs a tool that changes something on a path the agent decides, in a team with Strict skill publishing on | On publish only; the draft saves. The error names the line |

A skill's publish request shows its reviewer the text against the published version it replaces, kept as it was when
the request opened, with the hints on the new text's lines. Each published version records who asked for the publish
(`requestedBy`), who approved it (`approvedBy`, empty when the team's publish policy let it go live without a review)
and who made it live (`publishedBy`). `opsai skills versions <id>` lists all three.

## What success looks like

The agent works through the steps in order. Each step that has a check waits for it. A failed check retries, goes
back or leaves by a named exit, and the end of the run records the exit. A person who reads the conversation afterwards can see
which steps ran and why the skill ended.

## What to do next

- [Skill examples](skills.md): write, publish and attach a skill that has no steps.
- [Workflow examples](workflows.md): fixed steps with a person's approval.
- [Coming from another framework](coming-from-other-frameworks.md): how this compares with procedures in other agent frameworks.

## Write the skill as text

The console's skill page and the `source` field of a draft save take the same skill as plain text, written like a
prompt. Every line is an instruction to the agent, and the lines in this table are also enforced:

| You write | It becomes |
|---|---|
| A line that mentions a tool, an agent, a workflow or a skill (`@tool:find_customer`) | A step that may use it. Plain lines above it are part of that step's instruction |
| A numbered or bulleted line (`1.`, `-`, `•`) at the top level, with or without a mention | A step of its own. Plain lines above it are part of that step's instruction; a list indented under a plain line stays part of that line |
| Plain paragraphs with no list marker and no mention | Instructions the agent reads as it sees fit; no steps are made |
| The same line ending in `(locked)` | The step's tool is offered only on this line, even when it only reads |
| `if <condition>:` with an indented block, then `else:` at the same indent | A path: the nearest tool line above it in its block decides it, so plain lines between the two stay part of that step, and the other block is skipped |
| `stop "reason"` (or `stop <exit> "reason"`), under an `if` or `else` | An exit that ends the skill with that reason. A bare `stop <exit>` needs an ending the skill declares (or `done`, `failed`); any other bare `stop …` line is an instruction |
| `if not <condition>:` with only `try again` (`try again 2 times`) or `go back to step 3` under it | The condition becomes the step's own check: a failure asks again up to that many times, or goes back to that step |

```text title="customer-lookup.txt"
Greet them and ask for the email or order number they used.
Look them up with @tool:find_customer
if found:
    Confirm their name and read the last order from @tool:order_history
    if they want a refund:
        Follow @knowledge:refund_policy, then use @tool:issue_refund
    else:
        Answer from @knowledge:help_center
else:
    Ask for the email they used at checkout.
    if not verified:
        stop "Could not verify the caller"
Thank them.
```

A procedure pasted from a document reads the way it looks. `If …:`, `Otherwise:` and `Stop "…"` work like `if …:`,
`else:` and `stop "…"`. A list marker (`•`, `-`, `1.`) is not read. Non-breaking or full-width spaces and Windows
line endings count as ordinary ones. The rules below keep a flat list reading as a list:

| Line | Reads as |
|---|---|
| `If …:` or `Otherwise:`, with or without a list marker, with indented lines under it | A path |
| The same line with nothing indented under it, as in a flat numbered list (`2. If active:` / `3. Open the claim` / `4. Otherwise:`) | A plain line (a step of its own when it has a list marker), with a hint to indent the path |
| `Stop` or `- Stop` with no reason, under an `if` or `else` | An exit |
| `stop`, `Stop "Reason"` or `- Stop` at the top level, outside any path, with or without a reason | A plain line, with a hint to indent it under an `if` |
| `stop "Reason"` under an `if` or `else` | An exit |

So `2. If active:` followed by an indented `Open the claim` is a path, while the same lines written flat stay five
steps that the agent reads in order.

In the console editor, you can click a mention to replace or remove it, and tap a line with a wavy underline to read
its hint. Every hint is also listed under the text. To leave the editor with the keyboard, press Esc then Tab. A new
skill opens with a short example of one mention line and one path.

| Condition | How it is decided |
|---|---|
| Made of words the tool above returns (`found`, `not found`, `status is VIP`, `amount is more than 500`), or written as a rule (`result.balance > 0`) | Checked: a rule runs in code on the tool's result, labelled "checked" in the editor |
| Anything else (`they want a refund`) | The agent decides from the conversation and says which way it went: `step_done` with `holds` true or false. The kernel refuses `step_done` on that step without it. Labelled "agent decides" |

A path that is not taken does not count as a failure. It takes no hold and counts no attempt.

A `stop` that a checked condition leads to is a guard, whichever side of its `if` it sits on (`if not verified: stop …`
and `if flagged: stop …` alike). A guard takes the hold, and a value that is missing takes the guarded path, as a
failed check does. A `stop` that an "agent decides" condition leads to ends the skill without a hold. A path that
reaches the end before the last line still asks for the skill's results before it ends as done.

Nothing in the text stops a save. A line the reader cannot use gets a hint on that line. So does a tool that changes
something on a path the agent decides, on either side of the `if` and at any depth under it. Hints never stop a save
or a publish, and the publish check lists them as warnings of kind `hint`. A team that turns on **Strict skill
publishing** (the `skillPublishStrict` setting on Governance › Policies) refuses that one hint at publish instead, as a
`bad_check` problem on its line.

These also block a publish:

- A mention of something that no longer exists. The problem names the line it is on (`position.field` `source`,
  `position.index` the line).
- A text that makes more than 30 steps. None of its tools or paths could be enforced, so it is a `bad_step` problem on
  the 31st step's line.

Each step's prompt carries only that step's lines. `POST /v1/skills/{id}/text` reads a text without saving it, by the
same reader a save runs. A skill saved as a list of steps is shown as text by that reader, and it keeps its stored
steps until its text is saved.
