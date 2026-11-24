# Skill examples

Status: current.

A skill is a reusable procedure, written once and attached to any agent that should follow it. It has a line that
says when to use it and the instructions to follow. These examples write a skill, attach it to an agent, and pick it
for one reply.

Connect first: see [Before you start](README.md#before-you-start). The examples use the agent from
[Agent examples](agents.md#create-and-publish-an-agent).

## What each surface can do

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| List and read skills | built | built | built |
| Write and publish a skill | built, by API operation name | built, by API operation name | upcoming |
| Attach a skill to an agent | built, by API operation name | built, by API operation name | upcoming |
| Pick a skill for one reply | built | built | built |
| Write and publish with `ops.skills` and `opsai skills apply` | upcoming | upcoming | upcoming |
| Skills that run step by step | upcoming | upcoming | upcoming |

"By API operation name" means the SDK has no short verb for the task yet. You call the operation under `ops.raw`,
with the name the API reference gives it.

## Write and publish a skill

**The problem.** Several agents should handle a return the same way. Copying the procedure into each agent's
instructions means fixing it in several places later.

**When to use it.** Use a skill for any procedure more than one agent follows, or one you want to version and review
on its own.

```python
from ops_ai import OpsAI

ops = OpsAI()

skill = ops.raw.agents.agents_create_skill({
    "name": "Return checklist",
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
published = ops.raw.agents.agents_request_skill_publish(skill["id"], {"note": "First version"})
print(skill["id"], published["status"], published["publishedVersion"])
```

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const skill = await ops.raw.agents.agents_create_skill({
  body: {
    name: 'Return checklist (TypeScript)',
    useWhen: 'A customer wants to return an item.',
    loading: 'on_match',
    instructions:
      '1. Ask for the order number.\n' +
      '2. Check the purchase date is within 30 days.\n' +
      '3. Ask whether the customer has the receipt.\n' +
      '4. Never promise a refund for a sale item.',
    inputs: [{ name: 'order_number', description: 'The order being returned' }],
  },
});
const published = await ops.raw.agents.agents_request_skill_publish({ path: { skill_id: skill.id }, body: { note: 'First version' } });
console.log(skill.id, published.status, published.publishedVersion);
```

The command line lists and reads skills today.

```bash
opsai skills list --search "Return checklist"
SKILL=$(opsai skills list --search "Return checklist" --json | jq -r '.[0].id')
opsai skills show "$SKILL"
```

| Field | What it does |
|---|---|
| `name` | The skill's name. A team uses each name once |
| `ownerTeam` | The id of the team that answers for the skill, one of `ownerTeams` in `GET /v1/skills/options` (each with its name). The team you act in when left out; another team you may not create skills in is refused with 400 `unknown_owner_team`. Reads return the id and `ownerTeamName` |
| `useWhen` | One line that says when the skill applies. The agent reads it to decide whether to load the skill |
| `loading` | `on_match` loads the skill when a request matches `useWhen`. `always` puts it in every reply |
| `instructions` | The procedure the agent follows. Required |
| `inputs` | Named values a person gives when they pick the skill |
| `toolIds`, `knowledgeBases` | Tools and knowledge bases the skill needs |
| `refusal` | What the agent says when the skill tells it to refuse |

## Attach the skill to an agent

**The problem.** A published skill does nothing until an agent holds it.

**When to use it.** Attach after the skill is published. The agent keeps the version you attach, so a later version
of the skill reaches the agent only when you attach that version. Attaching changes the agent's draft, so publish
the agent again.

```python
agent = next(a for a in ops.agents.list(search="Returns helper") if a["name"] == "Returns helper")

held = ops.raw.agents.agents_attach_skill(agent["id"], skill["id"], {"version": published["publishedVersion"]})
ops.agents.publish(agent["id"], note="Uses the return checklist")
for pin in held["pins"]:
    print(pin["name"], pin["pinnedVersion"], pin["loading"])
print(held["limits"])
```

```ts
let agent;
for await (const a of ops.agents.list({ search: 'Returns helper (TypeScript)' })) agent = a;

const held = await ops.raw.agents.agents_attach_skill({
  path: { agent_id: agent.id, skill_id: skill.id },
  body: { version: published.publishedVersion },
});
await ops.agents.publish(agent.id, 'Uses the return checklist');
for (const pin of held.pins) console.log(pin.name, pin.pinnedVersion, pin.loading);
console.log(held.limits);
```

The answer lists the skills the agent holds and the limits: how many skills an agent may hold, how many it may load
in one reply, and how much text they may add.

## Pick a skill for one reply

**The problem.** The agent loads a skill when it judges that the request matches. Sometimes the person already knows
which procedure they want and should not depend on that judgement.

**When to use it.** Use it to start a known procedure, and to pass the values it needs. The pick applies to that one
reply.

```python
thread = ops.chat.start(agent["id"])
events = list(ops.chat.say(thread["id"], "I want to return my boots.", skill=skill["id"], inputs={"order_number": "1182"}))

message = events[-1]["message"]
for used in message["skills"]:
    print(used["name"], used["version"], used["how"], used["inputs"])
```

```ts
const thread = await ops.chat.start(agent.id);
const events = await ops.chat.say(thread.id, 'I want to return my boots.', { skill: skill.id, inputs: { order_number: '1182' } });

for (const used of events.at(-1).message.skills) console.log(used.name, used.version, used.how, used.inputs);
```

```bash
opsai chat say --agent "Returns helper" --skill "$SKILL" --input order_number=1182 -m "I want to return my boots."
```

Each reply records the skills it used. `how` is `picked` when a person chose the skill, and the record keeps the
skill's version and the inputs it was given.

## Upcoming: skill verbs

> [!NOTE]
> **Upcoming.** This section is merged and is not in the current release (v1.0.0). The verbs were run against
> the merged code on [Step-by-step skills](step-by-step-skills.md).

Skills get their own verbs, so a skill is a file you apply and publish like an agent.

```python
skill = ops.skills.create({"name": "Return checklist", "instructions": "..."})
ops.skills.save_draft(skill["id"], {"instructions": "..."}, note="Adds the receipt step")
ops.skills.publish(skill["id"], note="Adds the receipt step")
ops.skills.references("refund", for_skill=skill["id"])
```

```ts
const skill = await ops.skills.create({ name: 'Return checklist', instructions: '...' });
await ops.skills.saveDraft(skill.id, { instructions: '...' }, { note: 'Adds the receipt step' });
await ops.skills.publish(skill.id, 'Adds the receipt step');
await ops.skills.references('refund', skill.id);
```

```bash
opsai skills apply return-checklist.yaml --note "Adds the receipt step"
opsai skills publish <id> --note "Adds the receipt step"
opsai skills export <id> --format yaml
opsai skills references <id> --search refund
```

| Verb | What it will do |
|---|---|
| `create`, `save_draft` / `apply` | Create a skill, or save a new draft of the skill a file names by id, slug or name |
| `publish` | Ask to publish the newest draft. A skill that cannot be published is refused, and the error names each problem |
| `export` | Print a stored skill as a file `apply` reads |
| `references` | Search what the skill's text may mention: tools, knowledge bases, other skills, agents and workflows |

## Next steps

- [Step-by-step skills](step-by-step-skills.md): numbered steps with checks, exits and sub-skills. Upcoming.
- [Agent examples](agents.md): the agent these skills attach to.
- [Workflow examples](workflows.md): fixed steps with a person's approval.
