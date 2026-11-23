# Examples for builders

Status: current.

Short paths that show the same job in Python, TypeScript and on the command line.

## Start here

<!-- site: cards -->
- **[Ask once](../build-with-ops-ai.md)** — send one message and read the reply.
  Folder: [`examples/chat/01-ask-once/`](../../../examples/chat/01-ask-once/).
- **[Write, publish and use a skill](skills.md)** — publish a skill, give it to an agent, pick it once.
  Folder: [`examples/skills/01-publish-and-pick/`](../../../examples/skills/01-publish-and-pick/).

```python
from ops_ai import OpsAI

ops = OpsAI()
agent = next(a for a in ops.agents.list() if a.get("status") == "published")
print(ops.agents.chat(agent["id"], "What documents open a business account?")["reply"])
```

```bash
AGENT=$(opsai agents list --json | jq -r '.[] | select(.status=="published") | .id' | head -1)
opsai agents chat "$AGENT" --message "What documents open a business account?"
```

## Paths by job

<!-- site: cards -->
- **[Agent examples](agents.md)**: Create an agent, publish it, chat with it, and give it knowledge and tools.
- **[Workflow examples](workflows.md)**: Write a workflow, run it, wait for a person's decision, and call an agent from a step.
- **[Step-by-step skills](step-by-step-skills.md)**: Skills that run as numbered steps with checks and exits.
- **[Coming from another framework](coming-from-other-frameworks.md)**: LangGraph, OpenAI Agents SDK or Strands → Ops AI.

## Before you start

Install an SDK and connect once: [Python SDK](../../sdk/python.md#connect) or
[TypeScript SDK](../../sdk/typescript.md#connect). The `opsai` CLI ships with the Python package.

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

## Catalog

Capability ids and folders: [`examples/capabilities.yaml`](../../../examples/capabilities.yaml)
([`examples/registry.json`](../../../examples/registry.json) for opsai.chanl.ai). Prefer first-class nouns
(`ops.skills`, `ops.agents`, `opsai …`); `ops.raw` is an escape hatch only.
