# Publish and pick a skill

Publish a skill, give it to an agent, and pick it for one reply.

```python
from ops_ai import OpsAI

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
        "inputs": [{"name": "order_number", "description": "The order being returned"}],
    }
)
ops.skills.publish(skill["id"], note="First version")

agent = ops.agents.apply(
    {
        "name": "Returns helper",
        "role": "Answer questions about returns",
        "instructions": "Help with returns. Keep answers short. Follow attached skills.",
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
done = next(e for e in reversed(events) if e.get("type") == "done" and e.get("message"))
print(done["message"]["skills"])
```

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

```bash
SKILL=$(opsai skills apply resources/skill.yaml --note "First version" --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"
AGENT=$(opsai agents --json apply resources/agent.yaml | jq -r .id)
opsai agents add-reference "$AGENT" skill "$SKILL"
opsai agents publish "$AGENT" --note "Uses the return checklist"
opsai chat say --agent "$AGENT" --skill "$SKILL" --input order_number=1182 \
  -m "I want to return my boots."
```

Same files in this folder: `publish_and_pick.py`, `publish_and_pick.mjs`, `publish_and_pick.sh`.

Lesson: [docs/guide/examples/skills.md](../../../docs/guide/examples/skills.md).

<details>
<summary>Run the folder check</summary>

```bash
uv run python examples/skills/01-publish-and-pick/setup.py
uv run pytest examples/skills/01-publish-and-pick/test_example.py
```

Capability id: `skill.publish-and-pick`.
</details>
