# Examples for builders

Status: current. Hub layout is a redesign showcase: paths by job. Only the skill path below is fully rewritten;
other pages still use the older topic layout until they migrate.

Short, runnable paths for people who build on Ops AI from code. Each path states a goal, says when to use it, and
shows the same steps in Python, TypeScript and on the command line through first-class SDK and CLI verbs.

## Start here

<!-- site: cards -->
- **[Write, publish and use a skill](skills.md)**: Create a reusable procedure with `ops.skills` / `opsai skills`,
  give it to an agent, and pick it for one reply. Showcase of the redesigned path shape.

## Paths by job

<!-- site: cards -->
- **[Agent examples](agents.md)**: Create an agent, publish it, chat with it, and give it knowledge and tools.
  (Older layout — migration planned.)
- **[Workflow examples](workflows.md)**: Write a workflow, run it, wait for a person's decision, and call an agent
  from a step. (Older layout — migration planned.)
- **[Step-by-step skills](step-by-step-skills.md)**: Skills that run as numbered steps with checks and exits.
- **[Coming from another framework](coming-from-other-frameworks.md)**: What you did in LangGraph, the OpenAI Agents
  SDK or Strands, and the Ops AI way to do it.

The onboarding ladder that installs copyable folders is [Build with Ops AI](../build-with-ops-ai.md).

## Before you start

Install an SDK and connect it once: see [Python SDK](../../sdk/python.md#connect) or
[TypeScript SDK](../../sdk/typescript.md#connect). The command line tool `opsai` comes with the Python package.

Every example starts from a connected client and acts as one person in one team:

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

Use a team you keep for testing. The examples create agents, skills, workflows and a knowledge base in the team you
are connected to.

## How to read the examples

| You see | It means |
|---|---|
| Three code blocks: Python, TypeScript, command line | The same task on each surface. Prefer the first-class nouns (`ops.skills`, `ops.agents`, `opsai …`); `ops.raw` is an escape hatch only |
| A surface is missing from an example | That surface cannot do the task yet. The page's table of surfaces says so |
| Partial | The verb exists but drops fields, creates duplicates, or otherwise differs across languages — the page names the gap |
| Upcoming | The feature is not available on this branch yet. The page describes the intended shape |
| A reply is not shown | Replies depend on the model your deployment uses, so the examples print fields and leave the wording out |

Publishing an agent, a skill or a workflow sends a publish request. Your team decides who may approve it. On a
development stack requests are approved at once, so the examples go straight on to use what they published.
