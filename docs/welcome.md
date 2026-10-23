# Welcome to Ops AI

Status: current.

**Ops AI runs agents and workflows for regulated operations teams, with a person approving every change that
matters.** You build a workflow once, and it can pass a risk review: each run records who approved it, which version
ran, what it could reach, and where the record is.

## The problem it solves

A bank's card team works through hundreds of disputes a week. An insurer's claims team reads the same policy wording
fifty times a day. AI can already do much of this work, and pilots go well until the risk review asks who approved
the change to the customer's account, which version of the agent ran, and what data it could reach. Most agent tools
cannot answer, so the pilot stays a pilot, or the team builds approvals, versions and audit by hand for each use case.

## How Ops AI helps

| You need | Ops AI gives you |
|---|---|
| A person in charge of the steps that matter | Human Tasks: the workflow waits, a person decides with the facts in front of them, and the approved call carries a token bound to exactly what they saw |
| The same result every time where it counts | Fixed steps for lookups, branches and system calls, with an AI step only where judgement is needed |
| Control over what agents can reach | One gateway for every tool, data and model call, with per-team access and a call log |
| A record a reviewer accepts | Versioned agents and workflows, each run kept on the version it started with, and every decision on the case |
| Your own infrastructure | One machine, Docker or Kubernetes, on PostgreSQL, with a built-in test model that needs no key or network |

## Get started

<!-- site: cards -->
1. **[Install](guide/install.md)**: Run Ops AI on one machine and sign in to the console.
2. **[How work flows](guide/how-work-flows.md)**: How a request becomes a run, a task for a person and a record.
3. **[Agents and workflows](console/agents-and-workflows.md)**: Build an agent, give it tools and knowledge, and put it in a workflow.
4. **[Deployment options](guide/deployment-options.md)**: Choose how it runs for your team.

[What's built today](guide/whats-built-today.md) lists every capability as built, partial or
planned.
