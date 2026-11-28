# Access, approvals and audit

Status: current.

A risk reviewer usually asks the same two questions about an AI agent: who could change this customer's account, and who said yes? In Ops AI an agent or a workflow can draft a change to one of your systems, and your team decides which of those changes wait for a person. This page shows you how to make changes wait, who can approve them, what each role may do, and what Ops AI records so you can answer the reviewer later.

Out of the box, an agent's change to a connected app runs as soon as the agent decides to make it. Reading data never waits. Turning approvals on is a team setting, and it takes about a minute.

## Make an agent's changes wait for a person

This walkthrough turns approvals on for one team and follows a single change through to the record.

<!-- site: steps -->
1. As a team admin, open **Settings › Approvals** and turn on **Ask before an agent changes anything in an app**. Choose who answers: the person in the chat, or a reviewer role.
2. In chat, ask one of that team's agents to change something in a connected app, such as updating a customer's mailing address.
3. The change stops. If the person in the chat answers, the chat shows **Allow** and **Deny**. If a reviewer answers, a human task appears in **Work › Human Tasks** with the exact input the agent wants to send.
4. A reviewer opens the task, reads the input and approves it. The change runs once with that input, and the chat carries on.
5. Open **Govern › Activity** to see the request, the decision, who decided and what the system answered.

If the input changes after someone approves, the approval no longer matches it and the call is refused.

## What a reviewer can show afterwards

For any change, the activity record names the agent or workflow, the tool, the person it acted for, the decision and the reasons for it, the approvers, and the outcome. It also holds a fingerprint of the input rather than the input itself, so the record shows that the approved input is the one that was sent.

If you leave approvals off, the same record shows the call and who asked for it, but nobody decided it. Teams that handle customer money or account changes usually want a named approver on every one of those calls, which is the reason to turn this on before the first pilot rather than after the first review.

## Whether a change waits

<!-- site: decision caption="How Ops AI decides whether a tool call waits for a person" -->
- **Does the tool only read data?**
  - **Yes**: It runs at once and the call is logged.
  - **No, it changes data**: The channel and your settings decide.
    - **Did an AI assistant send it over MCP?**
      - **Yes**: It always waits for a reviewer. The only exception is a call that creates a draft, which does nothing until it is published and reviewed.
      - **No, it came from chat or a workflow**: The most specific setting wins: the tool's own, then the app's, then the team's. With none set, it runs and is logged with who asked.

Two more rules apply on top. A tool that needs two approvers always asks a reviewer, and the same person cannot approve twice. In a workflow nobody is in the chat, so a step that would ask "the person" goes to a reviewer instead.

## Roles

A person holds one or more roles in each team they belong to. A role is a grid of areas (agents, workflows, tools, files, reviews, cases, settings, access, audit and others) and actions (view, create, edit, publish, delete, run, decide, manage). Every check on the server reads that grid, and a refused action tells the person which permission is missing.

| Role | What it may do |
|---|---|
| Admin | Everything in the team. Actions held in the Security team still need a role there |
| Builder | Everything in the team except people and access, the team's webhooks and usage, connections, secrets and approval rules |
| Reviewer | Reads the team's work, decides its reviews, manages its cases and reads its activity |
| Viewer | Reads the team's work and chats with its agents |
| Chat user | Chats with the agents published to the team and sees only their own conversations |
| Security admin | Attached to Admins of the Security team. Changes egress, secrets and storage for every team and decides tool security reviews |
| Owner | One person. Transfers, closes and restores the workspace and changes the model aliases every team runs on |

You can edit Builder, Reviewer, Viewer and Chat user, and you can create your own roles in **Govern › Access › Roles**, either from scratch or as a copy of another role. A custom role cannot hold the cells that belong to the Security team or the owner. Admin, Security admin and Owner stay as shipped.

## How approvals are bound to what was approved

- An approval covers one tool, one step of one run and a hash of the exact input the approver saw.
- An approval token lives 15 minutes. When a run resumes later, Ops AI renews the token from the recorded decision for up to 24 hours, so the approver is not asked again. Past 24 hours the call needs a fresh review.
- By default the person who asked may also decide, as their role allows. A team can turn on the two-person rule, so someone else must decide. Admins of the team can still decide their own requests.
- The Security team can set a floor that no team can loosen. The floor can require that whoever asked never decides, and that an agent's change to an app always waits for a person or a reviewer.
- A step-up check asks an approver to sign in again before deciding. Operations that ask for it, such as payments, need a sign-in less than five minutes old.

## Publishing is reviewed too

A published agent, workflow, skill, guardrail, widget or tool version is the thing people run, so changing it is a change that can wait for a second person. By default a major change opens a review and a minor one, such as a new name, publishes at once. Each team and area can instead review every publish or none.

Some changes are reviewed whatever the team chose: changes to approval rules, access and egress, to an agent's guardrails, blocked topics and never rules, and turning off masking.

## Approval settings and their defaults

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Ask before an agent changes anything in an app | Changes wait for the person in the chat or for a reviewer of a chosen role | Off | A team admin, in Settings › Approvals |
| Approval by app | Per app: follow the team, change without asking, ask the person, or ask a reviewer | Every app follows the team | A team admin, in Settings › Approvals |
| Two-person rule | The person who asked may not decide their own request | Off: the person who asked may decide | A team admin, in Settings › Approvals |
| Approval floor | The least any team's rules may ask | No floor | A Security admin, in Govern › Policies |
| Step-up on every approval | Every approver signs in again before deciding | Off: only operations that ask for it | A Security admin, in Govern › Policies |
| Publish reviews | Per team and area: every publish, major changes only, or never | Major changes only | A builder or admin of the team, in Settings › Publish reviews |
| Review deadline | Hours a review may wait before it shows as overdue | 8 hours | A builder or admin of the team, in Govern › Policies |
| Require passing evals to publish | An agent publishes only after its saved cases ran on that version and every blocking step passed | Off | A builder or admin of the team, in Govern › Policies |

## What Ops AI records

| Record | What it holds |
|---|---|
| Audit log | Sign-ins, sign-outs, step-ups and password resets, and refresh tokens used twice. Invites, role changes, group-driven membership changes and removals. API keys created and revoked. Policy changes. Knowledge settings changes. Each entry is written in the same transaction as the change it records |
| Tool call log | Every call to your systems: for whom, which agent or workflow, the tool, a hash of the input, the decision and its reasons, the approvers, the outcome and the account used |
| Security changes | Allow-list, connection and storage settings changes, and every use or change of a stored secret. Secret use and change records are kept for 90 days |
| Decisions | Who decided each review, what they saw and their reason |
| Run journal | Each step of each run with its input, output and outcome, each chat event and each case event |
| Model calls | One row per call, refusals included: key, model, tokens, cost, time taken and outcome. No prompt or answer text |

On PostgreSQL the audit log is append-only. The service that writes it may add and read entries and may not change or delete them.

## Limits today

- A tamper-evident hash chain over the audit log, export to write-once storage and a retention setting per organisation are planned. Today the audit log, run journals and call logs are kept without an expiry.
- Approval tokens are signed with a key that two services share. Signing with a key only the review step holds is planned.

## Next

<!-- site: cards -->
- **[Data handling and masking](data-handling-and-masking.md)**: What people see masked, and how long data is kept.
- **[Egress and connections](egress-and-connections.md)**: Where a tool call may go and how it signs in.
- **[Identity and sign-in](identity-and-sign-in.md)**: The fresh sign-in an approval can ask for.
