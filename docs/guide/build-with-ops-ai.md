# Build with Ops AI

Status: current. Each step has a runnable example folder in the repository, tested on every change.

**Climb from one chat message to an agent and a workflow that call each other, in seven steps you can run.**

## You know what you want to build, not where to start

A developer new to Ops AI has an agent or a workflow in mind and no path to it. The pieces (chat, knowledge, tools,
agents, workflows) each have a page, and each page assumes the one before it.

This guide is the path: seven short steps, each through the Ops AI command line, with the same calls available in the
Python and TypeScript SDKs. Each step links to an example folder in the repository that you can run and copy.

## The plan

<!-- site: steps -->
1. **Talk to it**: one chat message, then a knowledge page.
2. **Give it a tool**: one read operation, in Mock and then for real.
3. **Make an agent and a workflow**: each applied from a file.
4. **Make them call each other**: a workflow step asks an agent, and an agent starts a workflow.

## Before you start

| You need | How |
|---|---|
| An install you can sign in to | Your company's Ops AI, or one on your machine from the [Quickstart](quickstart.md) |
| The command line | [Install the CLI](install-cli.md), then `opsai login` |
| The Builder role in a team | Builders create agents, workflows and knowledge bases |

## Try it

Run the steps in order; each one builds on the account and team you signed in with.

<!-- site: steps -->
1. **Chat**: send one message and read the reply.
   `opsai chat say -m "What can you help me with?"`
   ([example](../../examples/chat/01-ask-once/README.md))
2. **Knowledge**: add one page to a knowledge base and search it.
   `opsai kb add-text kb_... --title "ATM limits" --text "The daily limit is 500 dollars."`, then
   `opsai kb search kb_... "What is the daily limit?"`
   ([example](../../examples/knowledge/01-search-a-page/README.md))
3. **Tool**: run one read operation in Mock, then for real.
   `opsai tools run <app> <tool> --input id=42`, then the same with `--real`
   ([example](../../examples/tools/01-find-a-customer/README.md))
4. **Agent**: apply an agent from a file, publish it, and ask it one question.
   `opsai agents apply agent.yaml`, `opsai agents publish <id>`, `opsai agents chat <id> --message "..."`
   ([example](../../examples/agents/01-answer-from-instructions/README.md))
5. **Workflow**: validate, apply and test-run a three-step workflow.
   `opsai workflows validate workflow.yaml`, `opsai workflows apply workflow.yaml`,
   `opsai workflows run <id> --input request.json`
   ([example](../../examples/workflows/01-normalize-a-request/README.md))
6. **A workflow asks an agent**: an Agent step calls a published agent and keeps its cited answer
   ([example](../../examples/compositions/01-workflow-asks-agent/README.md)).
7. **An agent starts a workflow**: a chat calls a published workflow as a tool
   ([example](../../examples/compositions/02-agent-starts-workflow/README.md)).

## What success looks like

At each step the command prints the record it made or the answer it got. A refused step prints why, such as a workflow
input missing a required field, naming the field. After step 7 a chat starts a published workflow and a workflow
step asks a published agent.

## What skipping it costs

Without the ladder, the first agent is built before the first tool runs, and a failure in one piece looks like a
failure in all of them. Each step is small enough that a failure points to the piece that caused it.

The [workflows](workflows.md) and [agents](agents.md) pages list every further example: approvals, checklists,
delegation, evaluations.

## How agents and workflows meet

Agents and workflows call each other only through their public APIs, so either one works without the other.

<!-- site: compare caption="The two ways an agent and a workflow call each other" -->
- **A workflow asks an agent**: Step 6 of the ladder
  - **How**: An Agent step names a published agent and maps the prompt from the run's data
  - **What runs**: The agent's published version
  - **What comes back**: The agent's final answer, as the step's output
- **An agent starts a workflow**: Step 7 of the ladder
  - **How**: The workflow is on the agent's published tool list
  - **What runs**: The workflow's live version, for the signed-in person
  - **What comes back**: The run's result, or a handle when the run waits for a person

## The same operations on every surface

| Operation | Console | `opsai` | Python SDK | TypeScript SDK | HTTP API |
|---|---|---|---|---|---|
| Validate, apply, publish, run and trace a workflow | built | built | built | built | built |
| Apply an agent and chat with it | built | built | built | built | built |
| Evaluate an agent | planned | planned | built | planned | built |
| Run an agent in wait, stream or background mode | planned | built | built | planned | built |
| Replay a workflow run | planned | planned | planned | planned | planned |

## Next

<!-- site: cards -->
- [Examples for builders](examples/README.md): short examples on each surface, in Python, TypeScript and the command line.
- [Build your first tool](build-your-first-tool.md): a REST tool on your own API.
- [Card disputes](use-cases/card-disputes.md): a full workflow with an agent and an approval.
- [Python SDK](../sdk/python.md) and [TypeScript SDK](../sdk/typescript.md).
