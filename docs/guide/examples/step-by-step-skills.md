# Step-by-step skills

Status: upcoming. Skills with numbered steps are written and waiting to be released. This page describes how they
will work, and its code has not been run against a release.

> [!NOTE]
> **Upcoming.** Everything on this page describes a feature that is not in the current release. Names and fields may
> change before it ships. For what works today, see [Skill examples](skills.md).

A skill today is a block of instructions the agent reads and follows as it sees fit. A step-by-step skill is a
numbered procedure. The agent works on one step at a time, a check decides whether the step is done, and the skill
ends with a named exit.

## The problem

Some procedures must happen in order, every time: look up the charge, confirm the amount with the person, then
refund. Written as free text, the order is a request the model may skip. Written as a workflow, the procedure loses
the conversation. A step-by-step skill keeps the conversation and makes the order and the checks part of the skill.

## When to use it

| Use | When |
|---|---|
| A skill with instructions only | The agent needs guidance, and the order of actions does not matter |
| A step-by-step skill | A person is in the conversation, the actions must happen in order, and some of them must be checked before the next one starts |
| A workflow | No conversation is needed, or the work must survive long waits and restarts |

## Write a skill with steps

A skill file gains five fields: `steps`, `exit`, `returns`, `success` and `notWhen`.

```yaml title="refund-a-charge.yaml"
name: Refund a charge
ownerTeam: Card Support
useWhen: The customer asks for a card charge to be refunded.
notWhen: The charge is older than 120 days.
instructions: Quote the amount back before any refund. Never refund a charge twice.
inputs:
  - name: charge_id
    description: The charge to refund
    required: true
steps:
  - do: Look up the charge.
    use: {kind: tool, id: lookup_charge}
    check: {text: "result.amount <= 500 and result.status == 'settled'"}
    ifNot: {action: exit, exit: escalate}
  - do: Tell the person the amount and ask them to confirm.
    check: {text: The person confirmed the amount.}
    ifNot: {action: retry, retries: 2}
  - do: Refund the charge.
    use: {kind: tool, id: refund_charge}
    check: {text: "result.refunded is true"}
exit:
  escalate: Hand the request to a person.
returns:
  - name: refunded
    type: yes_no
    description: Whether the charge was refunded
success:
  - The person was told the amount before the refund.
```

Python:

```python
import yaml
from ops_ai import OpsAI

ops = OpsAI()

skill = ops.skills.create(yaml.safe_load(open("refund-a-charge.yaml")))
ops.skills.publish(skill["id"], note="First version")
```

TypeScript:

```ts
import { readFileSync } from 'node:fs';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const skill = await ops.skills.create(JSON.parse(readFileSync('refund-a-charge.json', 'utf8')));
await ops.skills.publish(skill.id, 'First version');
```

Command line:

```bash
opsai skills apply refund-a-charge.yaml
opsai skills publish <id> --note "First version"
```

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
`@tool:lookup_charge`. Saving the skill adds what its steps name to the skill's tools and knowledge bases.
`opsai skills references <id> --search refund` lists what a step may name.

## Rule checks

A check is either a rule or a sentence. A rule is worked out by code from the step's result, so the model cannot
talk its way past it. A sentence is judged by the model.

```yaml
check: {text: "result.amount <= 500 and result.status == 'settled'"}   # a rule
check: {text: The person confirmed the amount.}                        # a sentence
```

| A rule can use | Examples |
|---|---|
| The step's result and the skill's inputs | `result.amount`, `result.items[0].id`, `inputs.charge_id` |
| Values | Numbers, text in quotes, `true`, `false`, `null`, lists |
| Comparisons | `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `is true`, `is null` |
| Logic and arithmetic | `and`, `or`, `not`, and arithmetic on numbers |
| Functions | `len`, `lower`, `contains`, `exists` |

A missing field reads as `null`, and a comparison with `null` is false. A rule reads only its own step's result and
the inputs, not the results of earlier steps. Which kind a check is gets decided when the skill is saved. A text that
reads like a rule and is not a valid one is refused, so a typing mistake cannot turn a rule into a sentence.

## Exits

A skill ends with one exit. `done` is accepted only after the last step has passed. `failed`, or an exit the skill
lists, can end it at any step. A step sends the skill to an exit when its check fails:

```yaml
ifNot: {action: exit, exit: escalate}
```

The exit and the values in `returns` are what the caller gets back: the agent, or the step of another skill that
ran this one.

## How the agent moves through the steps

The agent that holds a step-by-step skill gets three built-in tools.

| Tool | What it does |
|---|---|
| `switch_skill` | Starts a skill by its slug, with its inputs. A skill that is already running ends first, so one skill runs at a time. A skill with a required input that is missing does not start, and the agent asks the person for it |
| `step_done` | Says the current step is done. It is refused while the step's tool has not run, and for a step whose rule is checked on the tool's result |
| `exit` | Ends the running skill with one of its exits and its results |

A person can also start the skill by picking it for a reply, as in
[Pick a skill for one reply](skills.md#pick-a-skill-for-one-reply). While a step names a tool, that tool and knowledge
search are the only systems the agent is offered, so a later step's tool cannot run early. A conversation finishes a
skill on the version it started with, even when a newer version is published meanwhile.

## Approvals

A step's tool waits for approval the same way any tool does: when the tool needs a person's yes, the reply pauses
until they decide. Two rules are added for steps.

| What happens | What the skill does |
|---|---|
| A person denies the step's call | The skill ends as `failed` at once |
| A step's check fails, or its call is denied | The tools of the later steps are held. No other skill, and no call outside a skill, may use them in that conversation until this skill passes that step |

The hold is per tool. A refund held for one charge is held for every charge in that conversation.

## Sub-skills

A step can run another skill. Use it for a procedure several skills share, such as verifying a caller.

```yaml title="verify-then-refund.yaml"
name: Verify, then refund
ownerTeam: Card Support
useWhen: A caller who is not yet verified asks for a refund.
instructions: Do not discuss the account before the caller is verified.
steps:
  - do: Verify the caller.
    use: {kind: skill, id: sk_verify_caller}
    check: {text: "result.exit == 'done' and result.verified is true"}
    ifNot: {action: exit, exit: failed}
  - do: Refund the charge.
    use: {kind: tool, id: refund_charge}
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

## Next steps

- [Skill examples](skills.md): what skills do today.
- [Workflow examples](workflows.md): fixed steps with a person's approval, built today.
- [Coming from another framework](coming-from-other-frameworks.md): how this compares with procedures in other agent frameworks.
