# Examples for builders

Status: current.

Short paths that show the same job in Python, TypeScript and on the command line. Each path states a goal, why it matters, the steps and what you should see, so you can finish without hopping pages.

## Start here

### Ask once

**Goal.** Send one message to a published agent and print the reply.  
**Why.** The smallest check that your sign-in, team and a published agent work.

```bash
python examples/chat/01-ask-once/ask_once.py
```

**You should see.** A non-empty reply string. Full walkthrough (Python, TypeScript, CLI): [Ask once](../build-with-ops-ai.md#ask-once).

### Write, publish and use a skill

**Goal.** Publish a return checklist, give it to an agent, and pick it for one reply.  
**Why.** Keep a shared procedure in one place instead of copying it into every agent.

```bash
python examples/skills/01-publish-and-pick/publish_and_pick.py
```

**You should see.** A `done` message whose `skills` list has `how: picked` and `order_number: 1182`. Full walkthrough with step-by-step what and why: [Write, publish and use a skill](skills.md).

## Before you start

Install an SDK and connect once. The command-line tool ships with the Python package.

```python
from ops_ai import OpsAI

ops = OpsAI()  # saved sign-in, or OPS_BASE_URL, OPS_API_KEY and OPS_TEAM
```

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();
```

```bash
opsai agents list
```

Use a team you keep for testing. Publishing sends a publish request; on a development stack it is approved at once.

## Other paths by job

<!-- site: cards -->
- **[Agent examples](agents.md)**: Create an agent, publish it, chat with it, and give it knowledge and tools.
- **[Workflow examples](workflows.md)**: Write a workflow, run it, wait for a person's decision, and call an agent from a step.
- **[Step-by-step skills](step-by-step-skills.md)**: Skills that run as numbered steps with checks and exits.
- **[Coming from another framework](coming-from-other-frameworks.md)**: LangGraph, OpenAI Agents SDK or Strands mapped to Ops AI.

## Catalog

Capability ids and folders: [`examples/capabilities.yaml`](../../../examples/capabilities.yaml)
([`examples/registry.json`](../../../examples/registry.json) for opsai.chanl.ai). Prefer first-class nouns
(`ops.skills`, `ops.agents`, `opsai …`); `ops.raw` is an escape hatch only.
