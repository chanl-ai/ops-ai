# Write, publish and use a skill

Status: current.

Publish a skill, give it to an agent, and pick it for one reply. Runnable file:
[`examples/skills/01-publish-and-pick/publish_and_pick.py`](../../../examples/skills/01-publish-and-pick/publish_and_pick.py).

## Python

```python
"""Publish a skill, give it to an agent, and pick it for one reply."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from ops_ai import OpsAI


class SkillRecord(TypedDict):
    id: str


class AgentRecord(TypedDict):
    id: str


class ThreadRecord(TypedDict):
    id: str


class ChatEvent(TypedDict, total=False):
    type: str
    message: dict[str, Any]


def main() -> None:
    ops = OpsAI()

    skill = cast(
        SkillRecord,
        ops.skills.create(
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
        ),
    )
    ops.skills.publish(skill["id"], note="First version")

    agent = cast(
        AgentRecord,
        ops.agents.apply(
            {
                "name": "Returns helper",
                "role": "Answer questions about returns",
                "instructions": (
                    "Help with returns. Keep answers short. Follow attached skills."
                ),
            }
        ),
    )
    ops.agents.add_reference(agent["id"], "skill", skill["id"])
    ops.agents.publish(agent["id"], note="Uses the return checklist")

    thread = cast(ThreadRecord, ops.chat.start(agent["id"]))
    events = [
        cast(ChatEvent, event)
        for event in ops.chat.say(
            thread["id"],
            "I want to return my boots.",
            skill=skill["id"],
            inputs={"order_number": "1182"},
        )
    ]
    done = next(
        event
        for event in reversed(events)
        if event.get("type") == "done" and event.get("message")
    )
    print(done["message"]["skills"])


if __name__ == "__main__":
    main()
```

## TypeScript

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

## Command line

```bash
python publish_and_pick.py
# or:
SKILL=$(opsai skills apply resources/skill.yaml --note "First version" --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"
AGENT=$(opsai agents --json apply resources/agent.yaml | jq -r .id)
opsai agents add-reference "$AGENT" skill "$SKILL"
opsai agents publish "$AGENT" --note "Uses the return checklist"
opsai chat say --agent "$AGENT" --skill "$SKILL" --input order_number=1182 \
  -m "I want to return my boots."
```

**You should see.** A `done` message whose `skills` list has `how: picked` and `order_number: 1182`.

## When to use it

Use a skill for a procedure more than one agent follows, or one you want to version on its own. Prefer a
[workflow](workflows.md) when there is no conversation. Prefer [step-by-step skills](step-by-step-skills.md) when the
conversation must keep a fixed order with checks.

Connect once: [Before you start](README.md#before-you-start).

## Surfaces

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| Create and publish a skill | built | built | built |
| Give a skill to an agent | built | built | built (`opsai agents add-reference`) |
| Pick a skill for one reply | built | built | built |

Capability id: `skill.publish-and-pick`. Catalog: [`examples/capabilities.yaml`](../../../examples/capabilities.yaml).

## Next

<!-- site: cards -->
- [Ask once](../build-with-ops-ai.md): send one message (`chat.ask-once`).
- [Step-by-step skills](step-by-step-skills.md): numbered steps with checks and exits.
- [Examples hub](README.md): other paths.
