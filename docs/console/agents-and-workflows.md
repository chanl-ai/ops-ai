# Agents and workflows

Status: user guide. Rows marked "planned" are designed and not yet built; the rest work in the console today.

## Two things, used together

An **agent** is something you talk to. It has an instruction, a model, and attachments: tools it may call, knowledge
bases it may search, skills it may use, and guardrails it must respect. You chat with it, and it decides its own steps
inside the limits it was given.

A **workflow** is a process that runs the same way every time. It is a set of steps (nodes) joined by arrows (ports),
started by a trigger such as an email, a chat message, an API call or another workflow. Some steps are AI: an agent, an
extraction, a classification. The rest are rules, tool calls and people deciding.

They meet in two places: an agent can be a step in a workflow, and a published workflow can be a tool an agent calls.

## What an agent is made of

| Part | What it does | Where to set it | Status |
|---|---|---|---|
| Instruction | What the agent is for and how it answers | Agents, the agent's page | works |
| Model | The model alias it runs on | Agents, Settings | works |
| Tools | Operations it may call; each keeps its own approval policy, so a write waits for a person | Agents, Tools | works |
| Knowledge | Knowledge bases it may search; answers cite page and section | Agents, Knowledge | works |
| Skills | Reusable instructions and steps it loads when a request matches; always-on ones are in every turn | Skills, then the agent's Skills section | works (tests, generation and import planned) |
| Guardrails | Topics it must refuse, checked on the question and on the answer; it says which guardrail refused | Guardrails, then the agent's Guardrails section | works for blocked topics (other kinds planned) |
| Budget | Most model calls and tool calls per turn; it says so when it stops | Agents, Settings | works |

## Using an agent

| You want to | Do this |
|---|---|
| Ask it something | Chat, pick the agent, type. Answers stream with citations, tables and charts |
| Let it act | Give it a write tool. When it drafts a write, the thread shows Approve and Reject; approving may ask for your password again |
| Use it in a process | Add an Agent step to a workflow and choose the agent; the step returns what the agent's output schema says |

## Using a workflow

| You want to | Do this |
|---|---|
| Build one | Workflows, New workflow, then add steps from the palette and connect their ports (typed steps planned) |
| Test one | Test run with sample input; pin a step's output to skip it on the next try (planned, an earlier change slice 3) |
| Run one | It starts from its trigger, or from Start run; each run shows every step with its input and output |
| Follow a run | Cases lists runs waiting on a person; Reviews holds their decisions; Activity lists every tool call behind them |
| Let an agent use it | Publish it, then grant it to the agent as a tool. An agent can also find it by searching tools; removing the grant hides it |

## When to use which

| Situation | Use |
|---|---|
| A person asks questions and the steps vary | An agent in chat |
| The same steps every time, with an audit trail and a person deciding | A workflow |
| A process with one judgment step in the middle | A workflow with an agent step |
| An agent should be able to start a governed process | The workflow as a tool for that agent |

## See it work on the sample team

`make sample-team` installs a team with agents, skills, guardrails, knowledge, tools and workflows through the API, and
`make demo-walk` checks it on the fake model, one PASS or FAIL line per step with its evidence. Both need the stack up
on the current code (`make up`), which also starts the workflow worker.

| It runs | What a PASS shows |
|---|---|
| The install | The team has its four people, three agents and six live workflows |
| A chat turn to the dispute agent about a duplicate charge | The turn loaded the Dispute evidence checklist skill and cites the Card dispute handbook |
| A chat turn asking whether to buy shares | The reply is the guardrail's message and names the guardrail and topic |
| A chat turn asking for a cardholder's accounts | search_customers and list_accounts answered from the fake bank |
| A chat turn asking for a hold | The hold waits on an approval card; after the approver approves, the reply names the hold |
| A levy notice emailed to the team mailbox | The workflows thank the sender, open a case per debtor, work out and place a hold, and send the replies a person approved |

The exit status is the number of failed steps.

More: how runs are executed, [architecture/workflow-runner.md](../architecture/workflow-runner.md); the step types,
[workflow nodes](../design/workflows/workflow-nodes.md); tools and approvals, [architecture/tool-lifecycle.md](../architecture/tool-lifecycle.md).
