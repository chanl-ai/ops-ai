# Welcome to Ops AI

Status: current.

**Ops AI runs agents and workflows for regulated operations teams, with a person approving every change that
matters.** Each run records who approved it, which version ran, what it could reach and where the record is, so a
workflow built once can pass a risk review.

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
| Control over what agents can reach | One gateway for every tool and data call and one for every model call, with per-team access and a call log |
| A record a reviewer accepts | Versioned agents and workflows, each run kept on the version it started with, and every decision on the case |
| Your own infrastructure | Docker Compose on one machine or Kubernetes, on PostgreSQL, with a built-in test model that needs no key or network |

## Start here

<!-- site: cards -->
1. **[Quickstart](guide/quickstart.md)**: Run Ops AI on your laptop and run your first workflow in about ten minutes.
2. **[Build with Ops AI](guide/build-with-ops-ai.md)**: The example folders in order, from one message to an agent that starts a workflow.
3. **[How work flows](guide/how-work-flows.md)**: How a request becomes a run, a task for a person and a record.
4. **[Install on a server](guide/install.md)**: Install for a team with one script, on Docker Compose or Kubernetes.

## For a security or architecture review

| Question | Read |
|---|---|
| What runs, and what does each part store and call? | [System components](guide/system-components.md) |
| How are sign-in, roles, approvals, secrets and outbound calls controlled? | [Security and governance](guide/security-and-governance.md) |
| Where is data kept, how are teams kept apart, and what is audited? | [Data and database](guide/data-and-database.md) |
| Which model calls leave, and under what limits? | [Models](guide/models.md) |
| What is built today and what is planned? | [What's built today](guide/whats-built-today.md) |
