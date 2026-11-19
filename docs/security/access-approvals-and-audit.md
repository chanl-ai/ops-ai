# Access, approvals and audit

Status: current. Checked against the release's roles, policies, review and audit code.

Software in Ops AI can draft any change to your systems; a person decides which changes go through. This page covers
what each role may do in a team, which actions wait for a second person, how an approval is tied to the exact change
the approver saw, and what is recorded as evidence.

## Try it

Make every write in a team wait for a reviewer, then watch one wait.

<!-- site: steps -->
1. As a team admin, open Governance › Policies and turn on "Ask before an agent changes anything in an app", answered
   by a reviewer.
2. In chat, ask an agent of that team to change something in a connected app, such as updating a record.
3. The write stops and a Human task appears for the team's reviewers, showing the exact input the agent wants to send.
4. A reviewer approves it. The write runs once, with that input, and the chat continues.
5. Open Governance › Activity to see the request, the decision, the approver and the call's outcome.

## Roles

A person holds a role in each team they belong to. Each role is a grid of areas (agents, workflows, tools, secrets,
files, reviews, cases, settings, access, audit and others) by actions (view, create, edit, publish, delete, run,
decide, manage), and every check on the server reads that grid.

| Role | What it may do in the team |
|---|---|
| Admin | Everything in the team. Actions reserved for the Security team still need a role there |
| Builder | Reads the team's work; creates, edits, tests and publishes its agents, workflows, tools and knowledge |
| Reviewer | Reads the team's work and decides its reviews and tasks |
| Viewer | Reads the team's work and chats with its agents |
| Security admin | Changes the outbound allow-list, credentials and storage for every team, and decides tool security reviews |
| Chat user | Chats with the team's agents |

A refused action tells the person which permission is missing; the Roles page shows each role's grid.

## How approvals work

- By default a write runs at once. A team turns on asking for the whole team, for chosen apps or for one tool; the most
  specific setting wins. The answer comes from the person in the chat (Allow, Deny, Allow for this chat) or from a
  reviewer of a chosen role.
- Every write made through MCP waits for a person, whatever the team's setting.
- An approval is bound to the tool, the run's step and a hash of the exact input the approver saw. Any change to the
  input voids it. It lives 15 minutes; a late run renews it from the recorded decision for up to 24 hours, so nobody
  is asked twice.
- An operation can need several distinct approvers, and a fresh sign-in from each. The same person cannot approve
  twice.
- Publishing an agent, workflow, skill, guardrail, widget or tool waits for a second person's review when the change is
  major. A major change to a tool module goes to the Security team.

## Options

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| Ask before an agent changes anything in an app | Writes wait for the person in the chat, or for a reviewer of a chosen role | Off: writes run at once | A team admin, in Governance › Policies |
| Approval by app | Per app: follow the team, change without asking, ask the person, or ask a reviewer | Every app follows the team | A team admin, in Governance › Policies |
| Requester may decide | The person who asked may also approve | Off: someone else decides | A Security admin, in Settings › Approvals |
| Step-up on every approval | Every approver signs in again before deciding | Off: only operations that ask for it | A Security admin, in Governance › Policies |
| Publish reviews | Per team and area: every publish, major changes only, or never (security changes always) | Major changes only | A Security admin, per team, in Governance › Policies |
| Review deadline | Hours before a waiting review shows as overdue | 8 hours | A Security admin, in Governance › Policies |

## What is recorded

| Record | What it holds |
|---|---|
| Audit log | Sign-ins, sign-outs, step-ups and refused refresh tokens; invites, role changes and removals; API keys created and revoked; policy changes; knowledge settings changes with the value before and after. Written in the same transaction as the change |
| Tool call log | Every call to your systems: for whom, which agent or workflow, the tool, a hash of the input, the decision and its reasons, the approvers, the outcome, the account used |
| Security changes | Every credential created, rotated, deleted or used; every allow-list, connection and storage settings change |
| Decisions | Who decided each review, what they saw, their reason, and a fingerprint of a payment approver's fresh sign-in |
| Run journal | Each step of each run with its input, output and outcome; each chat event; each case event |
| Model calls | One row per call, refusals included: key, model, tokens, cost, time taken, outcome. No prompt or answer text |

The audit log is append-only on PostgreSQL: the service that writes it may add and read entries, never change or
delete them.

## Limits

- Custom roles built from the grid are planned.
- Approval tokens are signed with a key two services share. Signing with a key only the review step holds is planned.
- A tamper-evident hash chain over the audit log, export to write-once storage, and a retention setting per
  organisation for logs are planned. Today logs are kept.

## Next

<!-- site: cards -->
- **[Data handling and masking](data-handling-and-masking.md)**: What people see masked, and how long data is kept.
- **[Egress and connections](egress-and-connections.md)**: Where a tool call may go and how it signs in.
- **[Identity and sign-in](identity-and-sign-in.md)**: The fresh sign-in an approval can ask for.
