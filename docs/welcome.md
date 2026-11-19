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
1. **[Quickstart](guide/quickstart.md)**: install Ops AI on one machine and run a first workflow in about ten minutes.
2. **[How work flows](guide/how-work-flows.md)**: how a request becomes a run, a task for a person and a record.
3. **[Agents](guide/agents.md)** and **[Workflows](guide/workflows.md)**: the two ways Ops AI runs work.
4. **[Human tasks and approvals](guide/human-tasks.md)**: how a person stays in charge of the steps that matter.

## For a security or architecture review

Isolation, sign-in, approvals and audit, data handling and model calls are answered in one place for a reviewer.

<!-- site: cards -->
- **[Security](security.md)**: how Ops AI keeps teams, data and model calls under control, with the limits stated.
