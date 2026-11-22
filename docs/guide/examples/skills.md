# Write, publish and use a skill

Status: current. Redesign showcase: one end-to-end path on first-class SDK and CLI verbs (not `ops.raw`).

**Goal.** Write a reusable procedure once, publish it, give it to an agent, and pick it for a single reply.

**When to use it.** Use a skill for any procedure more than one agent follows, or one you want to version and review
on its own. Prefer a [workflow](workflows.md) when there is no conversation, or long waits that must survive restarts.
Prefer a [step-by-step skill](step-by-step-skills.md) when the conversation must keep a fixed order with checks.

Connect first: see [Before you start](README.md#before-you-start).

## What each surface can do

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| List and read skills | built | built | built |
| Create, save a draft and publish (`ops.skills` / `opsai skills`) | built | built | built |
| Give a skill to an agent (`agents.add_reference` / `addReference`) | built | built | — (use SDK, or attach in the console) |
| Pick a skill for one reply | built | built | built |
| Skills that run step by step | see [step-by-step skills](step-by-step-skills.md) | same | same |

The happy path below uses those verbs. OpenAPI operation names under `ops.raw` are an [escape hatch](#escape-hatch-raw-operations), not the tutorial.

## 1. Write and publish the skill

Create the skill, then ask to publish its newest draft. On a development stack the request is approved at once.

```python
from ops_ai import OpsAI

ops = OpsAI()

skill = ops.skills.create({
    "name": "Return checklist",
    "ownerTeam": "Customer Support",
    "useWhen": "A customer wants to return an item.",
    "loading": "on_match",
    "instructions": (
        "1. Ask for the order number.\n"
        "2. Check the purchase date is within 30 days.\n"
        "3. Ask whether the customer has the receipt.\n"
        "4. Never promise a refund for a sale item."
    ),
    "inputs": [{"name": "order_number", "description": "The order being returned"}],
})
published = ops.skills.publish(skill["id"], note="First version")
print(skill["id"], published["status"], published.get("publishedVersion"))
```

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const skill = await ops.skills.create({
  name: 'Return checklist (TypeScript)',
  ownerTeam: 'Customer Support',
  useWhen: 'A customer wants to return an item.',
  loading: 'on_match',
  instructions:
    '1. Ask for the order number.\n' +
    '2. Check the purchase date is within 30 days.\n' +
    '3. Ask whether the customer has the receipt.\n' +
    '4. Never promise a refund for a sale item.',
  inputs: [{ name: 'order_number', description: 'The order being returned' }],
});
const published = await ops.skills.publish(skill.id, 'First version');
console.log(skill.id, published.status, published.publishedVersion);
```

Command line. The skill is a YAML or JSON file; `apply` creates it or saves a new draft of the skill the file names
by id, slug or name.

```yaml title="return-checklist.yaml"
name: Return checklist
ownerTeam: Customer Support
useWhen: A customer wants to return an item.
loading: on_match
instructions: |
  1. Ask for the order number.
  2. Check the purchase date is within 30 days.
  3. Ask whether the customer has the receipt.
  4. Never promise a refund for a sale item.
inputs:
  - name: order_number
    description: The order being returned
```

```bash
SKILL=$(opsai skills apply return-checklist.yaml --note "First version" --json | jq -r .id)
opsai skills publish "$SKILL" --note "First version"
opsai skills show "$SKILL"
```

| Field | What it does |
|---|---|
| `name` | The skill's name. A team uses each name once |
| `ownerTeam` | The team that answers for the skill. Required to create |
| `useWhen` | One line that says when the skill applies. The agent reads it to decide whether to load the skill |
| `loading` | `on_match` loads the skill when a request matches `useWhen`. `always` puts it in every reply |
| `instructions` | The procedure the agent follows. Required (may be empty when the skill uses numbered `steps`) |
| `inputs` | Named values a person gives when they pick the skill |
| `toolIds`, `knowledgeBases` | Tools and knowledge bases the skill needs |
| `refusal` | What the agent says when the skill tells it to refuse |

To change a skill after create, save a draft then publish again:

```python
ops.skills.save_draft(skill["id"], {"instructions": "…updated…"}, note="Adds the receipt step")
ops.skills.publish(skill["id"], note="Adds the receipt step")
```

```ts
await ops.skills.saveDraft(skill.id, { instructions: '…updated…' }, { note: 'Adds the receipt step' });
await ops.skills.publish(skill.id, 'Adds the receipt step');
```

```bash
opsai skills apply return-checklist.yaml --note "Adds the receipt step"
opsai skills publish "$SKILL" --note "Adds the receipt step"
```

**You should see.** A skill id (`skl_…`), a publish request whose status is approved on a development stack, and
`opsai skills show` listing the published version.

## 2. Give the skill to an agent

A published skill does nothing until an agent holds it. `add_reference` grants the skill (and brings tools and
knowledge bases the skill names). Attaching changes the agent's draft, so publish the agent again.

This path creates a small agent so the steps stand alone. You can reuse an agent from
[Agent examples](agents.md#create-and-publish-an-agent) instead.

```python
agent = ops.agents.apply({
    "name": "Returns helper",
    "role": "Answer questions about returns",
    "instructions": "Help with returns. Keep answers short. Follow attached skills.",
})
added = ops.agents.add_reference(agent["id"], "skill", skill["id"])
for item in added["added"]:
    print(item["kind"], item["id"])
ops.agents.publish(agent["id"], note="Uses the return checklist")
```

```ts
const agent = await ops.agents.apply({
  name: 'Returns helper (TypeScript)',
  role: 'Answer questions about returns',
  instructions: 'Help with returns. Keep answers short. Follow attached skills.',
});
const added = await ops.agents.addReference(agent.id, 'skill', skill.id);
for (const item of added.added) console.log(item.kind, item.id);
await ops.agents.publish(agent.id, 'Uses the return checklist');
```

```bash
# Create or update the agent, then grant the skill from Python or TypeScript (CLI has no add-reference yet).
AGENT=$(opsai agents --json apply returns-helper.yaml | jq -r .id)
opsai agents publish "$AGENT" --note "Uses the return checklist"
```

**You should see.** `added` lists `skill` and the skill id when the agent did not already hold it; an empty `added`
means it already did. After publish, people chat with the published agent that holds the skill.

## 3. Pick the skill for one reply

The agent loads a skill when it judges that the request matches `useWhen`. Sometimes the person already knows which
procedure they want. Pass the skill (and its inputs) on that one reply.

These snippets use the console-shaped chat stack (`ops.chat` / `opsai chat`), so the reply carries the same message
shape the console shows.

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
message = next(e["message"] for e in reversed(events) if e.get("type") == "done" and e.get("message"))
for used in message.get("skills") or []:
    print(used["name"], used["version"], used["how"], used["inputs"])
```

```ts
const thread = await ops.chat.start(agent.id);
const events = await ops.chat.say(thread.id, 'I want to return my boots.', {
  skill: skill.id,
  inputs: { order_number: '1182' },
});
const done = [...events].reverse().find((e) => e.type === 'done' && e.message);
for (const used of done?.message?.skills ?? []) {
  console.log(used.name, used.version, used.how, used.inputs);
}
```

```bash
opsai chat say --agent "Returns helper" --skill "$SKILL" --input order_number=1182 -m "I want to return my boots."
```

Each reply records the skills it used. `how` is `picked` when a person chose the skill, and the record keeps the
skill's version and the inputs it was given.

**You should see.** A `done` event whose message lists the skill name, version, `how: picked`, and
`order_number: 1182`.

## Verbs at a glance

| Verb | What it does |
|---|---|
| `skills.create` / `opsai skills apply` (new file) | Create a skill |
| `skills.save_draft` / `opsai skills apply` (existing) | Save a new draft of the skill a file names by id, slug or name |
| `skills.publish` / `opsai skills publish` | Ask to publish the newest draft. A skill that cannot be published is refused, and the error names each problem |
| `skills.export` / `opsai skills export` | Print a stored skill as a file `apply` reads |
| `skills.references` / `opsai skills references` | Search what the skill's text may mention: tools, knowledge bases, other skills, agents and workflows |
| `agents.add_reference` / `addReference` | Grant the agent a skill (or tool, knowledge base, agent, workflow) its brief can use |

## Escape hatch: raw operations

Screens and generated clients that call by OpenAPI operation name use `ops.raw`. Prefer the verbs above in new code.

| Task | Raw operation (illustrative) |
|---|---|
| Create | `ops.raw.agents.agents_create_skill` |
| Publish | `ops.raw.agents.agents_request_skill_publish` |
| Attach by pin | `ops.raw.agents.agents_attach_skill` (version pin). Prefer `agents.add_reference` unless you need the pin body |

Python passes path fields positionally; TypeScript passes `{ path, query, body }`. See the [Python SDK](../../sdk/python.md)
and [TypeScript SDK](../../sdk/typescript.md).

## Next

<!-- site: cards -->
- [Step-by-step skills](step-by-step-skills.md): numbered steps with checks, exits and sub-skills.
- [Agent examples](agents.md): deeper agent publish, knowledge and tools. (Older layout.)
- [Workflow examples](workflows.md): fixed steps with a person's approval. (Older layout.)
- [Examples hub](README.md): other paths and how to read status labels.
