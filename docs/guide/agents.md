# Agents

Status: current. The commands and folders below are checked by the example tests; what is planned says so.

An agent is a model with instructions, tools, knowledge, skills, guardrails and a budget, published as a reviewed
version. Inside those limits it chooses its own next step. People reach it through chat, other systems through the
API, and a workflow through an Agent step ([how agents and workflows meet](build-with-ops-ai.md#how-agents-and-workflows-meet)).

## Lifecycle

Every command below reads its address and sign-in from a profile. In an example folder, `setup.py` writes
`.ops-profile.json` and `OPS_CONFIG` names it ([Quickstart](quickstart.md#run-your-first-workflow)); elsewhere the
command reads `~/.config/ops-ai/config.json`.

| Step | Command | What it does |
|---|---|---|
| Check | `opsai agents validate resources/agent.yaml` | Checks the local file and lists every problem |
| Save a draft | `opsai agents apply resources/agent.yaml` | Creates or updates the draft |
| Publish | `opsai agents publish <id> --note "Ready"` | Requests the publish; a second person reviews it unless the team's publish policy says otherwise |
| Try a draft | `opsai agents test <id> --message "..."` | One test turn, as the agent's Test panel runs it |
| Chat | `opsai agents chat <id> --message "..."` | One message to the published agent |
| Run | `opsai agents run <id> --message "..." --mode wait` | Starts the published agent and waits; `--mode stream` streams the answer, `--mode background` returns at once |
| Look back | `opsai agents trace <id>` | The agent's recent runs |

From Python:

```python
from ops_ai import OpsAI

ops = OpsAI()
ops.agents.apply("resources/agent.yaml")
ops.agents.chat("ag_guide", "What documents open a business account?")
```

`ops.agents.eval(id, cases)` scores a set of cases against a published agent. An `opsai agents eval` command is
planned. The agent run API is built in the REST API, Python and the command line, and planned in TypeScript
([developer surface coverage](developer-surface-coverage.md)).

## Examples

Run the chat, knowledge and tool folders from [Build with Ops AI](build-with-ops-ai.md#the-ladder) first; these
folders reuse what they set up. Each is under `examples/agents/`.

| Folder | What it shows | Status |
|---|---|---|
| `01-answer-from-instructions` | Ask a published agent one question | Built |
| `02-cite-the-handbook` | Answer from a handbook, citing the section | Built |
| `03-look-up-a-customer` | Call a read tool | Built |
| `04-draft-a-note-for-approval` | A write waits for a person; rejecting leaves no tool call, approving writes | Built |
| `05-follow-a-checklist` | Follow a checklist skill and refuse a blocked topic | Built |
| `06-narrow-one-conversation` | Narrow one conversation to a subset of models, knowledge and tools | Built |
| `07-start-customer-hold` | Start a workflow from chat as a tool | Built |
| `08-run-in-three-modes` | Run one agent in stream, wait and background modes | Built |
| `09-delegate-to-a-specialist` | Call a published specialist agent as a tool | Built |
| `10-morning-held-wires` | Run an agent from a scheduled job and keep its report | Built |
| `11-eval-a-known-customer` | Score a set of customer look-up cases | Built |

[Agent example coverage](agent-example-coverage.md) lists the capabilities each folder teaches.
