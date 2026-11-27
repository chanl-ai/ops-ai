# Examples for builders

Status: current.

You have decided to build on Ops AI from code, and you want to see a working example before you read a reference.
Each page here takes one task, such as publishing an agent or running a workflow, and shows it in Python, in
TypeScript and on the command line, so you can copy the one that matches your stack and change the names.

Without examples you piece the first call together from the API reference, then learn about the publish request and
the approval step when the first run is refused. These pages show the whole path once, in the order you will meet it.

## Choose the task you want to code

<!-- site: cards -->
- **[Agent examples](agents.md)**: Create an agent, publish it, chat with it, and give it knowledge and tools.
- **[Skill examples](skills.md)**: Write a reusable procedure, attach it to an agent, and pick it for one reply.
- **[Workflow examples](workflows.md)**: Write a workflow, run it, wait for a person's decision, and call an agent from a step.
- **[Step-by-step skills](step-by-step-skills.md)**: Skills that run as numbered steps with checks and exits. Upcoming.
- **[Coming from another framework](coming-from-other-frameworks.md)**: What you did in LangGraph, the OpenAI Agents SDK or Strands, and the Ops AI way to do it.

## Connect once, then copy any example

<!-- site: steps -->
1. **Install an SDK.** Pick the Python or the TypeScript SDK. The command line tool `opsai` comes with the Python
   package.
2. **Connect it once.** See [Python SDK](../../sdk/python.md#connect) or
   [TypeScript SDK](../../sdk/typescript.md#connect).
3. **Pick a team you keep for testing.** The examples create agents, skills, workflows and a knowledge base in the
   team you are connected to.

Every example starts from a connected client, and it acts as one person in one team:

```python
from ops_ai import OpsAI

ops = OpsAI()  # reads your saved sign-in, or OPS_BASE_URL, OPS_API_KEY and OPS_TEAM
```

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();
```

```bash
opsai agents list
```

When the first example runs and prints an agent id, you are set up. If it is refused, the sign-in or the team is the
usual cause, and the SDK page explains how to fix both.

## What the labels on the examples mean

| You see | It means |
|---|---|
| Three code blocks: Python, TypeScript, command line | The same task on each surface. Each block was run against a development stack before it was published |
| A surface is missing from an example | That surface cannot do the task yet. The page's table of surfaces says so |
| Upcoming | The feature is not in the current release. The page describes how it will work, and the code has not been run against a release |
| A reply is not shown | Replies depend on the model your deployment uses, so the examples print fields and leave the wording out |

Publishing an agent, a skill or a workflow sends a publish request, and your team decides who may approve it. On a
development stack requests are approved at once, so the examples go straight on to use what they published. On a
team that requires a reviewer, wait for the approval before you run the step that uses the published version.
