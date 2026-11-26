# Overview

Status: current.

## Routine work fills your team's day

An operations team spends its day on work that follows a pattern. A court notice arrives and someone opens a case, a
complaint email needs triage, an account needs a hold, or a colleague asks what the procedure says. Software could do
the reading and drafting. In a regulated business, though, software cannot change a customer's account unless a person
decides, and every step has to leave a record that an auditor can read.

## Why one-off automations fall short

Without a platform that carries those controls, each automation is a one-off script, or a pilot that your risk function
has to review from scratch. Your team keeps retyping the same request across systems, and someone rebuilds the audit
answer by hand each time it is asked for.

## What Ops AI does

Ops AI is an operational AI platform that hands routine back-office work to software. Your team decides which changes to
its other systems wait for a person, such as anything that moves money, and every step leaves a record. It runs on your
own infrastructure, against a database your DBA controls and a model endpoint you choose. Nothing calls home.

## In three parts

<!-- site: cards -->
- **Agents**: a configured model with instructions, tools, knowledge, skills and guardrails. It decides its own next step inside the limits it was given. People reach it through chat, other systems through the API.
- **Workflows**: a versioned graph of typed steps that runs the same way every time and journals each step. It survives a crash without repeating a write, and waits days for a person at no cost.
- **Shared services and gateways**: reviews and human tasks, cases, knowledge, files, documents, identity and audit, used by both. Every call to your systems leaves through the data gateway, every model call through the AI gateway.

## Who uses it

| Person | What they do in Ops AI |
|---|---|
| Operations staff | Chat with the team's agents, open cases, answer the tasks a workflow hands them |
| Reviewer | Approves or rejects what an agent or a workflow wants to write, with a fresh sign-in for payments |
| Operations manager | Owns a process: its cases, its waiting tasks, its cost |
| Builder | Configures agents, workflows, tools, knowledge bases and document types, and publishes them through a review |
| Security admin | Controls which hosts the platform may call, the stored credentials, storage and sign-in |
| Operator | Installs, upgrades, backs up and watches the platform |

## The platform in one picture

Read it from the top: where work comes in, what runs it, and the one way out to your systems.

<!-- site: layers frame="Ops AI, on your infrastructure" caption="What runs today: work arrives from people, mailboxes, other systems and AI assistants; agents and workflows run it on the shared services; every call to your systems and every model call leaves through a gateway" -->
- **Where work comes from**: People, mailboxes, other systems and AI assistants
  - **A person in the console**: A lending team member asks for a payoff quote
  - **A team mailbox**: An outage report reaches a utility's service desk
  - **Another system, over the API**: A claims system opens a case
  - **An AI assistant, over MCP**: Every write it asks for waits for a person
- **Two ways to run work**: An agent can be a workflow step, and a workflow can be an agent's tool
  - **Agents**: A model with instructions, tools, knowledge, skills and guardrails
  - **Workflows**: Typed steps that run the same way every time, each one journaled
- **Shared services**: Used by both, stored in your own database
  - **Reviews, human tasks, cases**
  - **Knowledge, files, documents**
  - **Identity, teams, roles, audit**
  - **PostgreSQL**: The database your DBA controls
- **Gateways, the only way out**: Nothing reaches your systems or a model any other way
  - **Data gateway**: Tools, approvals, policy, allowed hosts, credentials
  - **AI gateway**: Model aliases, keys, budgets
- **Your systems and your model**
  - **Your systems**: Over REST, MCP and mail
  - **Your model endpoint**: The provider you choose

## Principles behind the design

| Idea | What it means for you |
|---|---|
| Agents and workflows are two ways of running work | An agent decides its own next step inside the limits it was given. A workflow runs fixed steps and survives a crash without repeating a write. Each works without the other, and they meet only through their public APIs: a workflow step can call an agent, and an agent can start a published workflow as a tool |
| A person approves the writes that matter | A team chooses which writes wait for a person: every write, the writes of some apps, or one tool's. A write that waits needs an approval token bound to the exact input the reviewer saw; changing one character of the input after approval voids it |
| Two gateways are the only way out | Tool calls go through the data gateway, which checks the approval, the policy and an allow-list of hosts. Model calls go through the AI gateway, which checks the caller's key, budget and the data's sensitivity |
| Use cases are configuration | A new process is workflows, document types, agents, tools and settings that a builder configures and publishes. No use case needs new code or a new screen. The court order notice used in this guide is one worked example among several |
| A team is the data boundary | Agents, workflows, knowledge and the work they produce belong to a team. Roles decide what a person may do inside the teams they belong to |
| Every change is versioned and reviewed | Agents, workflows, skills, guardrails, task types and tool modules are published as immutable versions through a review by a second person. A running case keeps the version it started on |

## Words used in this guide

| Word | Meaning |
|---|---|
| Tenant | Your organisation's installation boundary. Every row of data carries its tenant |
| Team | A group of people that owns agents, workflows, knowledge and cases |
| Agent | A configured model with instructions, tools, knowledge, skills and guardrails |
| Workflow | A versioned graph of typed steps: triggers, data steps, AI steps, human tasks, tool calls, cases |
| Run | One piece of work by an agent or a workflow, with a status, a budget and a journal |
| Thread | A conversation or a case's history; holds the saved state a run resumes from |
| Review, human task | A request for a person to decide something; the decision resumes the waiting run |
| Case | The record of one piece of work for people: what it is about, what it waits on, what happened |
| Tool | One operation on one of your systems, such as "get account" or "place hold", with its access class (read or write) and approval policy |
| Alias | A name such as `default` that points at a provider's model; changing the alias changes the model without changing an agent |

## What success looks like

A builder configures a new process by writing its agents and workflows and publishing them through a second person's
review, and the team can start using them the same day. When the risk team asks about a change, the answer is already on
the record: who approved it, which version ran and what it could reach.

## Next

<!-- site: cards -->
- **[Quickstart](quickstart.md)**: run Ops AI on one machine.
- **[How work flows](how-work-flows.md)**: follow a chat turn, a workflow run and an email that becomes a case, step by step.
- **[Agents](agents.md)** and **[Workflows](workflows.md)**: learn the two ways to run work.
