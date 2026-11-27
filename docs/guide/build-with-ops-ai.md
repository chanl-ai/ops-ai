# Build with Ops AI

Status: current.

This guide starts with a single chat message and ends with an agent and a workflow that call each other, in seven
steps you can run yourself.

## Where to begin when you are new to Ops AI

If you are new to Ops AI, you may already have an agent or a workflow in mind without knowing where to begin. Each
of the pieces you will use (chat, knowledge, tools, agents and workflows) has its own page, and each of those pages
assumes you have read the one before it.

This guide takes you through the pieces in order, in seven short steps. You run each step from the Ops AI command
line, and the same calls are available in the Python and TypeScript SDKs. Every step links to a runnable example
folder in the repository that you can copy, and those examples are tested on every change.

## The plan

<!-- site: steps -->
1. **Talk to it.** Send one chat message, then add a knowledge page.
2. **Give it a tool.** Run one read operation, first in Mock and then for real.
3. **Make an agent and a workflow.** You apply each one from a file.
4. **Make them call each other.** A workflow step asks an agent a question, and an agent starts a workflow.

## Before you start

| You need | How |
|---|---|
| An install you can sign in to | Your company's Ops AI, or one on your machine from the [Quickstart](quickstart.md) |
| The command line | [Install the CLI](install-cli.md), then `opsai login` |
| The Builder role in a team | Builders create agents, workflows and knowledge bases |

## Try it

Run the steps in order. Before each one, open its example folder and copy the files and ids that its command names,
such as `agent.yaml`, `workflow.yaml` and `request.json`.

<!-- site: steps -->
1. **Chat.** Send one message and read the reply.
   `opsai chat say -m "What can you help me with?"`
   ([example](../../examples/chat/01-ask-once/README.md))
2. **Knowledge.** Add one page to a knowledge base and search it.
   `opsai kb add-text kb_... --title "ATM limits" --text "The daily limit is 500 dollars."`, then
   `opsai kb search kb_... "What is the daily limit?"`
   ([example](../../examples/knowledge/01-search-a-page/README.md))
3. **Tool.** Run one read operation in Mock, then for real.
   `opsai tools run <app> <tool> --input id=42`, then the same with `--real`
   ([example](../../examples/tools/01-find-a-customer/README.md))
4. **Agent.** Apply an agent from a file, publish it, and ask it one question.
   `opsai agents apply agent.yaml`, `opsai agents publish <id>`, `opsai agents chat <id> --message "..."`
   ([example](../../examples/agents/01-answer-from-instructions/README.md))
5. **Workflow.** Validate, apply and test-run a three-step workflow.
   `opsai workflows validate workflow.yaml`, `opsai workflows apply workflow.yaml`,
   `opsai workflows run <id> --input request.json`
   ([example](../../examples/workflows/01-normalize-a-request/README.md))
6. **A workflow asks an agent.** An Agent step calls a published agent and keeps the answer it gives, along with its
   citations
   ([example](../../examples/compositions/01-workflow-asks-agent/README.md)).
7. **An agent starts a workflow.** A chat calls a published workflow as one of its tools
   ([example](../../examples/compositions/02-agent-starts-workflow/README.md)).

## What success looks like

At each step, the command prints the record it created or the answer it received. When a step is refused, the command
tells you why. For example, if a workflow input is missing a required field, the message names that field. Once you
have finished step 7, you have a chat that starts a published workflow and a workflow step that asks a published agent.

## Why the order matters

If you skip ahead, you may build your first agent before you have run your first tool. A failure in one piece then
looks like a failure in all of them. Because each step is small, a failure that happens along the way points you to
the piece that caused it.

The [workflows](workflows.md) and [agents](agents.md) pages list every further example, including approvals,
checklists, delegation and evaluations.

## How agents and workflows meet

Agents and workflows call each other only through their public APIs. That means you can use either one on its own,
without the other.

<!-- site: compare caption="The two ways an agent and a workflow call each other" -->
- **A workflow asks an agent**: Step 6 above
  - **How**: An Agent step names a published agent and maps the prompt from the run's data
  - **What runs**: The agent's published version
  - **What comes back**: The agent's final answer, as the step's output
- **An agent starts a workflow**: Step 7 above
  - **How**: The workflow is on the agent's published tool list
  - **What runs**: The workflow's live version, for the signed-in person
  - **What comes back**: The run's result, or a handle when the run waits for a person

## The same operations on every surface

| Operation | Console | `opsai` | Python SDK | TypeScript SDK | HTTP API |
|---|---|---|---|---|---|
| Validate, apply, publish, run and trace a workflow | built | built | built | built | built |
| Apply an agent and chat with it | built | built | built | built | built |
| Evaluate an agent | built | built | built | built | built |
| Run an agent in wait, stream or background mode | planned | built | built | planned | built |
| Replay a workflow run | planned | planned | planned | planned | planned |

## Next

<!-- site: cards -->
- [Examples for builders](examples/README.md): short examples on each surface, in Python, TypeScript and the command line.
- [Build your first tool](build-your-first-tool.md): a REST tool on your own API.
- [Card disputes](use-cases/card-disputes.md): a full workflow with an agent and an approval.
- [Python SDK](../sdk/python.md): every call from this guide in Python.
- [TypeScript SDK](../sdk/typescript.md): the same calls in TypeScript.
