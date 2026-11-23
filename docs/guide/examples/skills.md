# Write, publish and use a skill

Status: current.

**Goal.** Publish a return checklist once, give it to an agent, and pick it for one reply so the reply records which skill ran and which inputs it used.

**Why.** Several agents should handle returns the same way. A skill keeps that procedure in one place you can version and review, instead of copying it into each agent's instructions. Prefer a workflow when there is no conversation; prefer step-by-step skills when the conversation must keep a fixed order with checks.

## Before you run

Connect once with a saved sign-in, or set the base URL, API key and team. Use a team you keep for testing. Publishing sends a publish request; on a development stack it is approved at once.

```python
from ops_ai import OpsAI

ops = OpsAI()
```

## Steps

### 1. Create and publish the skill

What: a named procedure with when-to-use text, instructions and optional inputs.  
Why: publishing makes a version an agent can attach.

```python
skill = ops.skills.create(
    {
        "name": "Return checklist",
        "ownerTeam": "Customer Operations",
        "useWhen": "A customer wants to return an item.",
        "loading": "on_match",
        "instructions": (
            "1. Ask for the order number.\n"
            "2. Check the purchase date is within 30 days.\n"
            "3. Ask whether the customer has the receipt.\n"
            "4. Never promise a refund for a sale item."
        ),
        "inputs": [
            {
                "name": "order_number",
                "description": "The order being returned",
            }
        ],
    }
)
ops.skills.publish(skill["id"], note="First version")
```

### 2. Create an agent and attach the skill

What: an agent that answers returns questions, with the skill on its reference list.  
Why: pick only works for skills the agent is allowed to use.

```python
agent = ops.agents.apply(
    {
        "name": "Returns helper",
        "role": "Answer questions about returns",
        "instructions": (
            "Help with returns. Keep answers short. Follow attached skills."
        ),
    }
)
ops.agents.add_reference(agent["id"], "skill", skill["id"])
ops.agents.publish(agent["id"], note="Uses the return checklist")
```

### 3. Start a thread and pick the skill for one message

What: one chat turn that forces this skill and supplies `order_number`.  
Why: the reply's `skills` field shows what ran.

```python
thread = ops.chat.start(agent["id"])
events = list(
    ops.chat.say(
        thread["id"],
        "I want to return my boots.",
        skill=skill["id"],
        inputs={"order_number": "1182"},
    )
)
done = next(
    event
    for event in reversed(events)
    if event.get("type") == "done" and event.get("message")
)
print(done["message"]["skills"])
```

## You should see

A `done` message whose `skills` list has `how: picked` and `order_number: 1182`.

## Full copy

Run the complete module from the repository root:

```bash
python examples/skills/01-publish-and-pick/publish_and_pick.py
```

### Python

```python
"""Publish a skill, give it to an agent, and pick it for one reply."""

from ops_ai import OpsAI


def main() -> None:
    ops = OpsAI()

    skill = ops.skills.create(
        {
            "name": "Return checklist",
            "ownerTeam": "Customer Operations",
            "useWhen": "A customer wants to return an item.",
            "loading": "on_match",
            "instructions": (
                "1. Ask for the order number.\n"
                "2. Check the purchase date is within 30 days.\n"
                "3. Ask whether the customer has the receipt.\n"
                "4. Never promise a refund for a sale item."
            ),
            "inputs": [
                {
                    "name": "order_number",
                    "description": "The order being returned",
                }
            ],
        }
    )
    ops.skills.publish(skill["id"], note="First version")

    agent = ops.agents.apply(
        {
            "name": "Returns helper",
            "role": "Answer questions about returns",
            "instructions": (
                "Help with returns. Keep answers short. Follow attached skills."
            ),
        }
    )
    ops.agents.add_reference(agent["id"], "skill", skill["id"])
    ops.agents.publish(agent["id"], note="Uses the return checklist")

    thread = ops.chat.start(agent["id"])
    events = list(
        ops.chat.say(
            thread["id"],
            "I want to return my boots.",
            skill=skill["id"],
            inputs={"order_number": "1182"},
        )
    )
    done = next(
        event
        for event in reversed(events)
        if event.get("type") == "done" and event.get("message")
    )
    print(done["message"]["skills"])


if __name__ == "__main__":
    main()
```

### TypeScript

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const skill = await ops.skills.create({
  name: 'Return checklist (TypeScript)',
  ownerTeam: 'Customer Operations',
  useWhen: 'A customer wants to return an item.',
  loading: 'on_match',
  instructions:
    '1. Ask for the order number.\n' +
    '2. Check the purchase date is within 30 days.\n' +
    '3. Ask whether the customer has the receipt.\n' +
    '4. Never promise a refund for a sale item.',
  inputs: [{ name: 'order_number', description: 'The order being returned' }],
});
await ops.skills.publish(skill.id, 'First version');

const agent = await ops.agents.apply({
  name: 'Returns helper (TypeScript)',
  role: 'Answer questions about returns',
  instructions: 'Help with returns. Keep answers short. Follow attached skills.',
});
await ops.agents.addReference(agent.id, 'skill', skill.id);
await ops.agents.publish(agent.id, 'Uses the return checklist');

const thread = await ops.chat.start(agent.id);
const events = await ops.chat.say(thread.id, 'I want to return my boots.', {
  skill: skill.id,
  inputs: { order_number: '1182' },
});
const done = [...events].reverse().find((e) => e.type === 'done' && e.message);
console.log(done.message.skills);
```

### Command line

```bash
SKILL=$(opsai skills apply resources/skill.yaml --note "First version" --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"
AGENT=$(opsai agents --json apply resources/agent.yaml | jq -r .id)
opsai agents add-reference "$AGENT" skill "$SKILL"
opsai agents publish "$AGENT" --note "Uses the return checklist"
opsai chat say --agent "$AGENT" --skill "$SKILL" --input order_number=1182 \
  -m "I want to return my boots."
```

## Surfaces

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| Create and publish a skill | built | built | built |
| Give a skill to an agent | built | built | built (`opsai agents add-reference`) |
| Pick a skill for one reply | built | built | built |

Capability id: `skill.publish-and-pick`.
