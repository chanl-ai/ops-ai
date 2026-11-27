# Coming from another framework

Status: current.

You have built agents with LangChain and LangGraph, the OpenAI Agents SDK or Strands Agents, and you are weighing
Ops AI. This page maps each pattern you already use onto Ops AI. For every pattern it says what you wrote there, how you
do it here, and which example to run. Anything that is not in the current release is marked upcoming.

The main difference is where the agent lives. In those frameworks an agent is an object in your program. In Ops AI an
agent is a reviewed, versioned record on the platform, and your code creates it, publishes it and talks to it. Approvals,
memory, versions and the call log come with the platform, so you do not build them again for each agent.

If you port a framework agent line by line instead, you end up with an agent inside your program and the platform's
approvals and audit trail sitting unused beside it.

## How to move one agent over

<!-- site: steps -->
1. **Find your pattern** in the table below and read its short entry.
2. **Run the example it points to**, to see the Ops AI way on one small agent.
3. **Move the agent's instructions, tools and knowledge** into the file the example applies, then publish it.
4. **Check the Upcoming rows** for anything your agent needs that the current release does not have yet.

Framework names on this page were read from each project's public documentation on 19 November 2026.

## All patterns at a glance

| # | Pattern | Ops AI | Example |
|---|---|---|---|
| 1 | [One agent that calls tools](#1-one-agent-that-calls-tools) | built | [Let the agent open a case](agents.md#let-the-agent-open-a-case) |
| 2 | [Model and tool loop with limits](#2-model-and-tool-loop-with-limits) | built | [Put an agent your team can chat with into a file](agents.md#put-an-agent-your-team-can-chat-with-into-a-file) |
| 3 | [Structured output](#3-structured-output) | partial | [Let an agent answer one step](workflows.md#let-an-agent-answer-one-step) |
| 4 | [Routing and triage](#4-routing-and-triage) | built | [Write the refund rule and run it](workflows.md#write-the-refund-rule-and-run-it) |
| 5 | [Handoffs](#5-handoffs) | upcoming | |
| 6 | [Agents as tools](#6-agents-as-tools) | built | [Let the agent open a case](agents.md#let-the-agent-open-a-case) |
| 7 | [Swarm and graph of agents](#7-swarm-and-graph-of-agents) | partial | [Let an agent answer one step](workflows.md#let-an-agent-answer-one-step) |
| 8 | [Plan, then carry out](#8-plan-then-carry-out) | built | |
| 9 | [Sequential and parallel workflows](#9-sequential-and-parallel-workflows) | built | [Workflow examples](workflows.md) |
| 10 | [Human approval and interrupts](#10-human-approval-and-interrupts) | built | [Hold a large refund for a person's decision](workflows.md#hold-a-large-refund-for-a-persons-decision) |
| 11 | [Conversation memory and sessions](#11-conversation-memory-and-sessions) | built | [Ask a question and follow up in the same conversation](agents.md#ask-a-question-and-follow-up-in-the-same-conversation) |
| 12 | [Long-term memory](#12-long-term-memory) | built | |
| 13 | [Guardrails](#13-guardrails) | partial | |
| 14 | [Tracing](#14-tracing) | partial | [See which path a run took](workflows.md#see-which-path-a-run-took) |
| 15 | [Evals](#15-evals) | partial | [Check that a change keeps your answers right](agents.md#check-that-a-change-keeps-your-answers-right) |
| 16 | [Streaming](#16-streaming) | built | [Start a long reply and read it later](agents.md#start-a-long-reply-and-read-it-later) |
| 17 | [MCP tools](#17-mcp-tools) | built | |
| 18 | [Runs that survive a restart](#18-runs-that-survive-a-restart) | partial | [Workflow examples](workflows.md) |
| 19 | [Scheduled agents](#19-scheduled-agents) | partial | |
| 20 | [Deployment](#20-deployment) | built | |
| 21 | [Skills loaded when needed](#21-skills-loaded-when-needed) | built | [Skill examples](skills.md) |
| 22 | [Procedures that run step by step](#22-procedures-that-run-step-by-step) | upcoming | [Step-by-step skills](step-by-step-skills.md) |

## 1. One agent that calls tools

| If you wrote | In |
|---|---|
| `create_agent(model, tools=[...])` | LangChain |
| `Agent(tools=[...])`, then `Runner.run` | OpenAI Agents SDK |
| `Agent(tools=[...])` | Strands |

The agent is a file you apply and publish. Its tools are operations your team has published, rather than functions
in your program, and you grant them to the agent by id. Run
[Put an agent your team can chat with into a file](agents.md#put-an-agent-your-team-can-chat-with-into-a-file), then [Let the agent open a case](agents.md#let-the-agent-open-a-case).

Writing a tool as one function, with its inputs read from the code, is upcoming. Today a tool is a REST operation,
an MCP tool or a plugin tool, as [Build your first tool](../build-your-first-tool.md) explains.

## 2. Model and tool loop with limits

| If you wrote | In |
|---|---|
| `ModelCallLimitMiddleware`, `recursion_limit` | LangChain |
| `max_turns` | OpenAI Agents SDK |
| `limits={"turns": 5, ...}` | Strands |

The platform runs the loop for you, and the limits are settings on the agent, under `guardrails` in its file:
`maxToolCallsPerTurn`, `maxModelCallsPerTurn`, `maxModelCallsPerConversation` and `maxCostPerConversation`. Set them
in the file you apply in [Put an agent your team can chat with into a file](agents.md#put-an-agent-your-team-can-chat-with-into-a-file).

## 3. Structured output

| If you wrote | In |
|---|---|
| `response_format=Model` | LangChain |
| `output_type=Model` | OpenAI Agents SDK |
| `structured_output_model=Model` | Strands |

Ask for a shape at the point where the answer is used. A workflow's agent step takes an `outputSchema` and
gets an object that matches it, or leaves by its error port. The classify and extract steps are bound to a schema
too. Start from [Let an agent answer one step](workflows.md#let-an-agent-answer-one-step).

Upcoming work adds an output shape set on the agent itself, so that chat and run calls return a typed object.

## 4. Routing and triage

| If you wrote | In |
|---|---|
| A router with `add_conditional_edges` | LangGraph |
| Structured output, then code picks the agent | OpenAI Agents SDK |
| Conditional edges in `GraphBuilder` | Strands |

In a workflow, a classify step sorts the request and a branch step sends it down a path. The
branch in [Write the refund rule and run it](workflows.md#write-the-refund-rule-and-run-it) does the same thing with
a number. In chat, the team's default agent is offered the specialists the person may use, and it picks one.

## 5. Handoffs

| If you wrote | In |
|---|---|
| A tool that returns `Command(goto=...)` | LangGraph |
| `handoffs=[agent]` | OpenAI Agents SDK |
| `handoff_to_agent` in a `Swarm` | Strands |

A second agent that takes over the conversation and answers the person directly is upcoming, and is not in the
current release. Today a specialist answers one question and the first agent carries on, as described under
[Agents as tools](#6-agents-as-tools).

## 6. Agents as tools

| If you wrote | In |
|---|---|
| A subagent wrapped with `@tool` | LangChain |
| `agent.as_tool(...)` | OpenAI Agents SDK |
| `tools=[agent]`, `agent.as_tool()` | Strands |

Grant a published agent to another agent as `agent:<id>`. The specialist answers with its own
knowledge, tools, guardrails and approvals, for the same person. `tool_options` in
[Let the agent open a case](agents.md#let-the-agent-open-a-case) lists the agents you may grant.

Also upcoming are specialists that take typed inputs, keep their context between calls and may ask a specialist of
their own. Today a specialist gets one question as text, and the chain is one level deep.

## 7. Swarm and graph of agents

| If you wrote | In |
|---|---|
| A `StateGraph` with agents as nodes | LangGraph |
| Peer agents that list each other in `handoffs` | OpenAI Agents SDK |
| `Swarm`, `GraphBuilder` | Strands |

A workflow takes the place of the graph. Agent steps are its nodes, with branches, joins, repeats, waits
and child workflows around them, and every step is recorded. Start from
[Let an agent answer one step](workflows.md#let-an-agent-answer-one-step).

A team of agents that pass work between themselves with shared notes, where the model chooses the order, is
upcoming.

## 8. Plan, then carry out

| If you wrote | In |
|---|---|
| `TodoListMiddleware`, or an orchestrator that starts workers with `Send` | LangChain and LangGraph |
| Agents chained in your own code | OpenAI Agents SDK |
| The `graph` tool | Strands |

Every agent has a built-in plan: a short checklist the person sees in chat, ticked off as the agent works. You do not
need to set it up. The plan belongs to one agent and does not start parallel workers. For work in parallel, use a
workflow that starts a child run for each item.

## 9. Sequential and parallel workflows

| If you wrote | In |
|---|---|
| `StateGraph` edges, fan-out and join | LangGraph |
| Plain Python and `asyncio.gather` | OpenAI Agents SDK |
| Plain Python or `GraphBuilder` | Strands |

A workflow is a typed graph in a file: triggers, data steps, branches, joins, repeats, waits, AI
steps, human review, tool calls and child workflows. Run [Workflow examples](workflows.md), and see
[Workflow example coverage](../workflow-example-coverage.md) for every step type.

## 10. Human approval and interrupts

| If you wrote | In |
|---|---|
| `interrupt()`, `HumanInTheLoopMiddleware` | LangGraph and LangChain |
| `needs_approval`, `RunState` | OpenAI Agents SDK |
| `event.interrupt(...)` in a hook | Strands |

You do not write the pause. A workflow's review step stops the run until a person decides, as you can see
by running [Hold a large refund for a person's decision](workflows.md#hold-a-large-refund-for-a-persons-decision). In
chat, when your team's policy says that changes must wait for approval, a tool that changes something pauses the reply
until a person approves it. The person who asked cannot approve their own request.

## 11. Conversation memory and sessions

| If you wrote | In |
|---|---|
| A checkpointer and a `thread_id` | LangGraph |
| `session=SQLiteSession(...)` | OpenAI Agents SDK |
| `session_manager=...` | Strands |

Every chat is a stored thread, and you pass the thread back to continue it, as in
[Ask a question and follow up in the same conversation](agents.md#ask-a-question-and-follow-up-in-the-same-conversation).
You do not choose or run a store.

## 12. Long-term memory

| If you wrote | In |
|---|---|
| `store.put`, `store.search` | LangGraph |
| The `Memory()` capability of sandbox agents | OpenAI Agents SDK |
| `MemoryManager(stores=[...])` | Strands |

Memory is a setting on the agent, `memory` in its file. An agent remembers facts, preferences and past episodes for
each person. The person can list, change and erase what is remembered, and a retention setting applies.
The examples either turn memory off or leave the default. In both cases you do not write the code that saves and
recalls what the agent remembers.

## 13. Guardrails

| If you wrote | In |
|---|---|
| `PIIMiddleware`, `before_agent` hooks | LangChain |
| Input, output and tool guardrails | OpenAI Agents SDK |
| Bedrock Guardrails, hooks | Strands |

On the platform, a guardrail is a published, versioned record that agents hold. The kind built today is blocked
topics, checked on the person's message and on the answer. Personal data is masked by a setting on the agent.

More kinds of guardrail are upcoming: required citations, a rule on the answer's shape, a rule on a tool's input,
and a mode that records a hit without blocking.

## 14. Tracing

| If you wrote | In |
|---|---|
| LangSmith tracing | LangChain |
| Built-in tracing, `add_trace_processor` | OpenAI Agents SDK |
| OpenTelemetry traces and metrics | Strands |

Each workflow run keeps a record of every step, as
[See which path a run took](workflows.md#see-which-path-a-run-took) shows. An agent lists its recent runs, as in
[Start a long reply and read it later](agents.md#start-a-long-reply-and-read-it-later), and every tool call and model call is logged.

Still upcoming are a trace of one agent reply as a tree, export over OpenTelemetry, and metrics.

## 15. Evals

| If you wrote | In |
|---|---|
| LangSmith datasets and evaluations | LangChain |
| Not named in its documentation | OpenAI Agents SDK |
| `strands-agents-evals` | Strands |

Give an agent a list of cases, each with checks on the reply, as in
[Check that a change keeps your answers right](agents.md#check-that-a-change-keeps-your-answers-right). Three checks
are built: the reply holds a text, the agent called a tool, and the agent refused. Today this runs from Python.

Upcoming work adds checks judged by a model, stored suites with a history of runs, a command line verb and a
TypeScript method.

## 16. Streaming

| If you wrote | In |
|---|---|
| `stream(stream_mode=...)` | LangGraph |
| `Runner.run_streamed` | OpenAI Agents SDK |
| `stream_async()` | Strands |

A chat reply streams its text, tool calls and citations as events, and a workflow run streams its events
too. See the modes in [Start a long reply and read it later](agents.md#start-a-long-reply-and-read-it-later), and `ops.chat.say` in
[Start a known procedure from the chat](skills.md#start-a-known-procedure-from-the-chat), which returns a reply's events.

The TypeScript SDK gets run modes in an upcoming release. Today TypeScript reads a reply's events through `ops.chat`.

## 17. MCP tools

| If you wrote | In |
|---|---|
| `MCPAdapter` | LangChain |
| `MCPServerStreamableHttp`, `HostedMCPTool` | OpenAI Agents SDK |
| `MCPClient` | Strands |

Add an outside MCP server once, as a tool source for the team. Its tools then pass through
the same approvals, limits, masking and call log as every other tool, and you grant them to an agent like any tool:
see [Let the agent open a case](agents.md#let-the-agent-open-a-case).

Calling a team's write tools over MCP from outside assistants in production is upcoming. Today that direction serves
read tools as test runs.

## 18. Runs that survive a restart

| If you wrote | In |
|---|---|
| A checkpoint per step, replay and fork | LangGraph |
| Temporal, Restate, DBOS or Dapr around the SDK | OpenAI Agents SDK |
| Session managers | Strands |

Workflows are durable without extra setup. Every step is recorded, a write is made once, and a run that waits for a
person holds no worker. An agent's reply is saved when it pauses for an approval, and it continues after the decision.

Agent replies that run on workers and survive a restart are upcoming. Today a reply runs inside the request, and a
background run from Python is lost if the calling program exits first. Replaying a workflow run, or starting again
from one step, is upcoming too.

## 19. Scheduled agents

| If you wrote | In |
|---|---|
| `client.crons.create` on Agent Server | LangChain |
| Your own scheduler calling `Runner.run` | OpenAI Agents SDK |
| A timer on your host, such as Lambda | Strands |

An agent or a workflow can be armed to run once at a due time, and the same key runs once. Use
`ops.agents.schedule(id, message, due_at=...)` in Python, or a schedule trigger in a workflow.

Repeating schedules are upcoming.

## 20. Deployment

| If you wrote | In |
|---|---|
| LangSmith Agent Server | LangChain |
| A library inside your own service | OpenAI Agents SDK |
| AgentCore, Lambda, containers | Strands |

The platform acts as the server. One install hosts every agent, and publishing an agent makes it
reachable from chat, the API, both SDKs, the command line, a workflow step and a team mailbox. See
[Deployment options](../deployment-options.md).

Releases of the SDKs on PyPI and npm and a Helm chart are upcoming. Today you install the SDKs from the repository.

## 21. Skills loaded when needed

| If you wrote | In |
|---|---|
| A `load_skill` tool | LangChain |
| Not named in its documentation | OpenAI Agents SDK |
| SOPs turned into skill files | Strands |

A skill is a published, versioned procedure that agents hold. It loads when a request matches
its use-when line, or in every reply. Run [Skill examples](skills.md).

Skill verbs on the SDKs and the command line are upcoming, as described in
[Upcoming: manage skills with their own verbs](skills.md#upcoming-manage-skills-with-their-own-verbs).

## 22. Procedures that run step by step

| If you wrote | In |
|---|---|
| A graph you draw, or one agent whose prompt and tools change per stage | LangGraph and LangChain |
| Steps written in code around the runner | OpenAI Agents SDK |
| Agent SOPs, steering | Strands |

A skill with numbered steps is upcoming. In such a skill, the agent sees one step at a time, a rule worked out by
code can check a step's result, and the skill ends with a named exit. Read
[Step-by-step skills](step-by-step-skills.md) for the details. Until it ships, use a skill with written instructions
where guidance is enough, and a workflow where the order must hold.

## Upcoming features

Each row is something one of the three frameworks offers that Ops AI does not have in the current release.

| Status | Feature | Pattern |
|---|---|---|
| Upcoming | An agent hands the conversation to another agent, which answers the person directly | 5 |
| Upcoming | Specialists with typed inputs, kept context and more than one level of depth | 6 |
| Upcoming | A team of agents that pass work between themselves with shared notes and limits | 7 |
| Upcoming | An output shape set on the agent, returned as a typed object | 3 |
| Upcoming | More guardrail kinds, and a mode that records without blocking | 13 |
| Upcoming | A trace tree for one reply, OpenTelemetry export and metrics | 14 |
| Upcoming | Evals with model judges, stored suites and a command line verb | 15 |
| Upcoming | Agent runs that survive a restart, and run modes in TypeScript | 16, 18 |
| Upcoming | Replay a workflow run, or start again from one step | 18 |
| Upcoming | Repeating schedules for agents and workflows | 19 |
| Upcoming | A tool written as one function | 1 |
| Upcoming | Outside assistants calling a team's write tools over MCP in production | 17 |
| Upcoming | SDKs on PyPI and npm, and a Helm chart | 20 |
| Upcoming | Skills that run step by step, and a brief on the agent | 22 |

## What success looks like

Your agent runs on Ops AI as a published version, with the approvals, memory and call log the platform keeps, and your
program only creates it, publishes it and talks to it.

## What to do next

- [Agent examples](agents.md), [Skill examples](skills.md) and [Workflow examples](workflows.md): run the code.
- [What's built today](../whats-built-today.md): every capability as built, partial or planned.
