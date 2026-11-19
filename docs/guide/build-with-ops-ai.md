# Build with Ops AI

Status: current. Each step has a runnable example folder in the repository, tested on every change.

A developer new to Ops AI needs a path from one chat message to an agent and a workflow that call each other. This
guide is that path, seven short steps, each through the Ops AI command line with the same calls available in the
Python and TypeScript SDKs. Each step links to an example folder you can run and copy.

## Before you start

| You need | How |
|---|---|
| An install you can sign in to | Your company's Ops AI, or one on your machine from the [Quickstart](quickstart.md) |
| The command line | [Install the CLI](install-cli.md), then `opsai login` |
| The Builder role in a team | Builders create agents, workflows and knowledge bases |

## The ladder

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

Expected at each step: the command prints the record it made or the answer it got. A refused step prints why, such as
a workflow input missing a required field, naming the field.

The [workflows](workflows.md) and [agents](agents.md) pages list every further example: approvals, checklists,
delegation, evaluations.

## How agents and workflows meet

Agents and workflows call each other only through their public APIs, so either one works without the other.

```mermaid
flowchart LR
  WF["Workflow"] -->|"Agent step: names a published agent<br/>and maps the prompt"| AG["Agent"]
  AG -->|"a workflow tool on its published tool list"| WF2["Published workflow,<br/>live version"]
  AG -.->|"final answer"| WF
```

| Direction | How | What comes back |
|---|---|---|
| A workflow asks an agent | An Agent step names a published agent and maps the prompt from the run's data | The agent's final answer, as the step's output |
| An agent starts a workflow | The workflow is on the agent's published tool list; calling it starts the workflow's live version for the signed-in person | The run's result, or a handle when the run waits for a person |

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
