# Examples for builders

Status: current.

You have decided to build on Ops AI from code, and you want to see a working example before you read a reference.
Each page here takes one task, such as publishing an agent or running a workflow, and shows it in Python, in
TypeScript and on the command line, so you can copy the one that matches your stack and change the names.

Without an example, you would piece the first call together from the API reference, and you would likely learn about
the publish request and the approval step only when your first run is refused. Each page walks through the whole path
once, in the order you will meet it.

## Choose the task you want to code

<!-- site: cards -->
- **[Agent examples](agents.md)**: Create an agent, publish it, chat with it, and give it knowledge and tools.
- **[Skill examples](skills.md)**: Write a reusable procedure, attach it to an agent, and pick it for one reply.
- **[Workflow examples](workflows.md)**: Write a workflow, run it, wait for a person's decision, and call an agent from a step.
- **[Step-by-step skills](step-by-step-skills.md)**: Skills that run as numbered steps with checks and exits.
- **[Coming from another framework](coming-from-other-frameworks.md)**: What you did in LangGraph, the OpenAI Agents SDK or Strands, and the Ops AI way to do it.

## Connect once, then copy any example

<!-- site: steps -->
1. **Install an SDK.** Pick the Python or the TypeScript SDK. The command line tool `opsai` comes with the Python
   package.
2. **Connect it once.** See [Python SDK](../../sdk/python.md#connect) or
   [TypeScript SDK](../../sdk/typescript.md#connect).
3. **Pick a team you keep for testing.** The examples create and publish agents, skills, workflows and a knowledge
   base in the team you are connected to, so use a test team and not your live one.
4. **Add a second sign-in for approvals.** Where an example approves a publish or decides a task as a second person, it
   uses a saved profile named `reviewer`: another person in the same team with the Reviewer role. Your team admin gives
   a person that role (see [Teams and access](../teams-and-access.md#the-roles-every-team-starts-with)), and that person
   signs in once with `opsai login --profile reviewer --email <their email>`. The code then uses
   `OpsAI(profile="reviewer")` or `new OpsAI({ profile: 'reviewer' })`, and the command line uses `--profile reviewer`.
   If your team has not turned on the two-person rule, the person who asked may also decide, and the examples still run
   with one profile.

Every example starts from a connected client, which acts as one person in one team:

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

When the first example runs and prints an agent id, you are set up. If it is refused, the usual cause is the sign-in
or the team, and the SDK page explains how to fix both.

## What the labels on the examples mean

| You see | It means |
|---|---|
| Three code blocks: Python, TypeScript, command line | The same task on each surface. Each block was run against a development stack before it was published, and the surfaces marked built are in release v1.2.0 |
| A surface is missing from an example | That surface cannot do the task yet. The page's table of surfaces says so |
| Upcoming | The feature is not in the current release, v1.2.0. The page describes how it will work, and the code has not been run against a release |
| A reply is not shown | Replies depend on the model your deployment uses, so the examples print fields and leave the wording out |

Publishing an agent, a skill or a workflow sends a publish request, and your team's publish policy decides whether it needs a review. A first publish does. A team can turn on a two-person rule (under Approvals, Advanced) so that someone other than the person who asked decides. On a
development stack, requests are approved at once, so the examples go straight on to use what they published. If your
team requires a reviewer, wait for the approval before you run the step that uses the published version.
