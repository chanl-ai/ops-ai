# Welcome to Ops AI

Status: current.

Ops AI lets you put agents and workflows to work on your team's operations, with a person approving every change that
matters. You build an agent once, and every run keeps the record a risk review will ask for: who approved it, which
version ran and what it could reach.

## You have a queue AI could clear

You run an operations team, or build tools for one. A card team works through hundreds of disputes a week. A claims
team reads the same policy wording fifty times a day. A lending servicing team answers payoff and hardship requests
that follow the same few paths. A model can already draft most of this work.

Then the pilot goes well, and the risk review asks three questions: who approved the change to the customer's
account, which version of the agent ran, and what data it could reach. Most agent tools can't answer them, so the
team either stops at the pilot or builds approvals, versions and an audit trail by hand for every new use case.

## What a stalled pilot costs you

While the pilot waits, your team keeps working the queue by hand. Each use case that needs its own
hand-built approvals and audit trail slows down the next one. And a single unreviewed change to a customer's account could end the programme.

## How Ops AI answers the risk review

We built Ops AI for teams that answer to a risk function, so the controls a reviewer asks about come with it:

| A reviewer asks | Ops AI records |
|---|---|
| Who approved this change? | The workflow waits on a human task. The person decides with the facts in front of them, and the call that runs is bound to exactly what they approved |
| Which version ran? | Agents and workflows are published as fixed versions that never change, and each run keeps the version it started on |
| What could it reach? | Every tool and data call goes through one gateway, and every model call through another, with access set per team and a log of every call |
| Where does it run? | On your own machines, either Docker Compose on one server or Kubernetes, with PostgreSQL. A built-in test model means you need no model key or network to start |

The [Security](security/README.md) pages give the full answers, including their limits.

## How you get there

<!-- site: steps -->
1. **Install it on one machine.** It takes one command and about ten minutes, and you don't need a model key.
2. **Build an agent.** Write its instructions, try out the draft, and publish it once a second person has reviewed it.
3. **Connect your apps and documents.** Give the agent tools for your systems and a knowledge base to answer from.
4. **Put a person on the steps that matter.** Any change to data waits for someone to approve it, and the workflow
   keeps the record.

## Start now

<!-- site: cards -->
- **[Install Ops AI](guide/quickstart.md)**: Set it up on one machine in about ten minutes, and finish with your first workflow run.

## What changes when it works

By the time a dispute reaches a person, it has already been checked against your handbook. When the risk team asks,
the approval is already on the case.

<!-- site: journey caption="A card dispute from arrival to a recorded approval, as the team sees it: each step is done before a person opens the case" -->
1. **Team mailbox · A dispute arrives**: The cardholder's email lands in the team mailbox, so nobody has to retype it.
   - **From**: Cardholder, card ending 4417
   - **Subject**: Charged twice for one purchase
   - **Amount**: $84.20
2. **Workflow · The workflow finds the cardholder**: It reads the account through the data gateway. Reading data never waits for a person.
   - **Account**: Found, open since 2019
   - **Same charge**: Twice, two minutes apart
   - **Earlier disputes**: None in 12 months
3. **Agent · The agent checks the handbook**: It answers from your dispute handbook and says which section it used.
   - **Handbook**: Duplicate charges, section 4.2
   - **Suggests**: Credit $84.20 to the card
4. **Human task · A person approves the credit**: The credit changes the account, so it waits for a named reviewer, who sees the exact input.
   - **Input**: Credit $84.20 to card ending 4417
   - **Reviewer**: Disputes lead
   - **Actions**: Approve, Reject
5. **Case · The case keeps the record**: When the risk team asks, the answer is already on the case.
   - **Approved by**: Disputes lead, 10:42
   - **Version**: Disputes agent, version 7
   - **Reached**: Card ledger, one write

<!-- site: cards -->
- **Without Ops AI**: Someone retypes the same request into three systems, the approval sits in an email thread, and each time someone asks for the audit trail, it has to be pieced together by hand.
- **With Ops AI**: The case already shows who approved the credit, on which version, and with what data. [Card disputes](guide/use-cases/card-disputes.md) walks through it.

## Read next

- [Build an agent](guide/use-cases/build-an-agent.md): take an agent from a first draft to a published version your team can chat with.
- [How work flows](guide/how-work-flows.md): see how a request becomes a run, a task for a person and a record.
