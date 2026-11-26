# Welcome to Ops AI

Status: current.

**Put agents and workflows to work on your team's operations, with a person approving every change that matters.**
You build the agent once, and every run keeps the record a risk review asks for: who approved it, which version ran
and what it could reach.

## You have a queue AI could clear

You run or build for an operations team. A card team works through hundreds of disputes a week. A claims team reads
the same policy wording fifty times a day. A lending servicing team answers payoff and hardship requests that follow
the same few paths. A model can already draft most of this work.

The pilot goes well. Then the risk review asks who approved the change to the customer's account, which version of the
agent ran, and what data it could reach. Most agent tools have no answer, so the team either stops at the pilot or
builds approvals, versions and audit by hand for each new use case.

## What waiting costs

Every week the pilot stays a pilot, the queue is still worked by hand. Each use case that gets its own hand-built
approvals and audit makes the next one slower, and a single unreviewed write to a customer's account can end the
programme.

## Ops AI is built for that review

We built Ops AI for teams that answer to a risk function, and the controls a reviewer asks about ship with it:

| A reviewer asks | Ops AI records |
|---|---|
| Who approved this change? | The workflow waits on a Human Task; the person decides with the facts in front of them, and the approved call is bound to exactly what they saw |
| Which version ran? | Agents and workflows are published as versions that do not change; each run keeps the version it started on |
| What could it reach? | Every tool and data call goes through one gateway and every model call through another, with per-team access and a call log |
| Where does it run? | On your own machines: Docker Compose on one server or Kubernetes, on PostgreSQL, with a built-in test model that needs no key or network |

The full answers, with their limits, are on the [Security](security/README.md) pages.

## How you get there

<!-- site: steps -->
1. **Install it on one machine.** One command, about ten minutes, no model key needed.
2. **Build an agent.** Write its instructions, try the draft, and publish it once a second person has reviewed it.
3. **Connect your apps and documents.** Give the agent tools for your systems and a knowledge base to answer from.
4. **Put a person on the steps that matter.** Writes wait for a yes, and the workflow keeps the record.

## Start now

<!-- site: cards -->
- **[Install Ops AI](guide/quickstart.md)**: One machine, about ten minutes, and a first workflow run at the end.

## What changes when it works

A dispute reaches a person already checked against the handbook, and the approval is on the case when the risk team
asks.

```mermaid caption="A card dispute from arrival to a recorded approval: each step is done before a person opens the case"
flowchart LR
  A[Dispute arrives] --> B[Workflow finds the cardholder and accounts]
  B --> C[Agent checks the handbook and cites sections]
  C --> D[Person approves the credit on one screen]
  D --> E[Case records who, which version, what data]
```

<!-- site: cards -->
| Without Ops AI | With Ops AI |
|---|---|
| The same request is retyped across three systems, the approval lives in an email thread, and the audit answer is rebuilt by hand each time someone asks. | The case already holds who approved the credit, on which version, with what data ([Card disputes](guide/use-cases/card-disputes.md) walks through it). |

## Read next

- [Build an agent](guide/use-cases/build-an-agent.md): from a first draft to a published agent your team chats with.
- [How work flows](guide/how-work-flows.md): how a request becomes a run, a task for a person and a record.
