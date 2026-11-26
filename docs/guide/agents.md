# Agents

Status: current. Rows marked planned are designed and not built.

**Give your team an assistant that answers from your own procedures and calls your systems, inside limits you set.**

## Some work never follows the same steps twice

A staff member asks a question, or a request needs a few lookups before anyone knows what to do. A fixed script cannot
cover that, and a loose chatbot with no limits cannot be trusted near a customer's account. Without something in
between, the team keeps answering the same questions by hand.

An agent is a model with instructions, tools, knowledge, skills, guardrails and a budget. Inside those limits it
chooses its own next step. People reach it through chat, other systems through the API, and a workflow through an Agent
step. Skipping the limits is the costly part: an agent with no budget, no approval on its writes and no knowledge of
your documents guesses, and a guess that writes to an account is the one a risk review stops.

## Try it

Save this as `agent.yaml`:

```yaml
name: Account opening helper
role: answer
instructions: Answer from these instructions only. Business accounts need two identity documents.
memory:
  enabled: false
```

Then save it as a draft and try it, before anyone publishes it:

```bash
opsai agents validate agent.yaml
opsai agents apply agent.yaml                 # prints the agent's id
opsai agents test <agent-id> --message "What documents open a business account?"
```

The same agent opens under **Build › Agents** in the console, where its **Test** panel runs the same turn.

## What an agent is made of

| Part | What it does | Status |
|---|---|---|
| Instructions | What the agent is for and how it answers | built |
| Model | The model alias it runs on. Changing what an alias points at changes the model without changing the agent | built |
| Tools | Operations on your systems it may call. Each keeps its own approval setting, so a write can wait for a person ([Tools and apps](apps.md)) | built |
| Knowledge | Knowledge bases it may search; answers cite page and section ([Knowledge](knowledge.md)) | built |
| Skills | Reusable instructions it loads when a request matches; always-on skills are in every turn | built. Skill tests, generation and import planned |
| Guardrails | Topics it must refuse, checked on the question and on the answer; the reply names the guardrail | built for blocked topics. Other kinds planned |
| Budget | The most model calls and tool calls in one turn; the reply says when it stopped | built |

## Lifecycle

| Step | Command | What it does |
|---|---|---|
| Check | `opsai agents validate agent.yaml` | Checks the file and lists every problem |
| Save a draft | `opsai agents apply agent.yaml` | Creates or updates the draft |
| Try the draft | `opsai agents test <id> --message "..."` | One test turn, as the Test panel runs it |
| Publish | `opsai agents publish <id> --note "Ready"` | Requests the publish. A second person reviews it unless the team's publish policy says otherwise |
| Chat | `opsai agents chat <id> --message "..."` | One message to the published agent |
| Run | `opsai agents run <id> --message "..." --mode wait` | Starts the published agent and waits; `--mode stream` streams the answer, `--mode background` returns at once |
| Look back | `opsai agents trace <id>` | The agent's recent runs |

A published version does not change. Editing makes a new draft, and a conversation already under way keeps the version
it started on.

From Python:

```python
from ops_ai import OpsAI

ops = OpsAI()
draft = ops.agents.apply("agent.yaml")
ops.agents.chat(draft["id"], "What documents open a business account?")
```

`ops.agents.eval(id, cases)` scores a set of cases against a published agent from Python. An `opsai agents eval` command,
and the run and eval methods in the TypeScript SDK, are planned.

A background run lives in the program that started it and is lost if that program exits before the reply is on the
thread. `opsai agents run --mode background` exits as soon as it prints the ids, so its run is lost; use it from a
program that keeps running. Runs that carry on without the caller are planned.

`ops.agents.schedule(id, message, due_at=...)` arms one run at a due time; the same key runs once. Repeating schedules
are planned.

[Agent examples](examples/agents.md) shows each of these in Python, TypeScript and the command line.

## Agent or workflow

| Situation | Use |
|---|---|
| A person asks questions and the steps vary | An agent in chat |
| The same steps every time, with a record and a person deciding | A [workflow](workflows.md) |
| A process with one judgement step in the middle | A workflow with an Agent step; the step returns what the agent's output schema says |
| An agent that should be able to start a governed process | Publish the workflow and give it to the agent as a tool |

When an agent drafts a write that needs approval, the chat shows Approve and Reject, and approving may ask for your
password again ([Human tasks and approvals](human-tasks.md)).

## What success looks like

The agent answers from your instructions and cites the page and section of your documents. A write waits for a person
before it reaches your system. A published version stays as it was while you edit the next one.

## Next

<!-- site: cards -->
- **[Build with Ops AI](build-with-ops-ai.md)**: example agents from one question to one that starts a workflow.
- **[Knowledge](knowledge.md)**: give the agent your team's documents.
- **[Tools and apps](apps.md)**: let the agent read and write your systems.
- **[Chat and channels](ops-assistant.md)**: where people talk to it.
