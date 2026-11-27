# Human tasks and approvals

Status: current. Rows marked planned are designed and not built.

When an agent or workflow reaches a step that matters, you can pause it there, show a person exactly what is about to
happen, and let it carry on only once that person has decided.

## Some steps need a named person on the record

Some actions should wait until a person has looked at them: a payment, a hold on an account, a reply to a customer, or a
field read from a blurry scan. If the agent runs straight through, a mistake in any of these lands in a customer's
account before anyone has checked it. Asking for approval by email does not close the gap, because nobody can later show
what the approver was looking at when they agreed. The same is true when a reviewer signs off on a summary, since the
summary does not show what the agent was about to send.

A human task pauses the agent or workflow at that step, shows a person exactly what will happen, and carries on only
with their decision. Use one wherever your process needs a named person on the record. A claims team might approve a
settlement this way, a lender might confirm a payoff quote, and a support team might check a refund.

## How an approval works

<!-- site: steps -->
1. **Choose which actions wait.** Your team admin decides whether approvals cover the whole team, some apps or a single
   tool, and who answers them.
2. **The agent asks.** When the agent reaches an action that changes data, the run pauses and a task shows the exact
   input it wants to use.
3. **A person decides.** The reviewer approves or rejects the task with a reason, from the console, the chat or the
   command line.
4. **The run carries on.** An approved action runs once, and a rejected one makes no change. Either way, the record
   keeps who decided, when and why.

## Try it

In this walkthrough you make every action that changes data in your team wait for a person, and then you approve one.

<!-- site: steps -->
1. **Turn on approvals.** As a team admin, open **Settings › Approvals**, turn on **Ask before an agent changes anything in
   an app** in the console, set **Who answers** to **Ask a reviewer**, and pick the role that reviews.
2. **Ask the agent to change something.** You need an agent that holds a write tool from an app your team has turned
   on ([Tools and apps](apps.md)). In a chat, ask it to do something, for example "Add a note to case 1042
   saying the customer called." Instead of making the change, the chat shows an approval card with the exact input.
3. **Approve it.** A reviewer opens **Work › Human Tasks**, or uses the command line:

   ```bash
   opsai tasks list --view open
   opsai tasks show <task-id>
   opsai tasks approve <task-id> --reason "Checked with the customer"
   ```

   Once the task is approved, the write runs once and the chat carries on with its result. To reject the task instead,
   run `opsai tasks decide <task-id> reject --reason "..."`, and nothing is written.

## How a decision is protected

Each decision is tied to exactly what the reviewer saw, and it counts only once.

<!-- site: annotated caption="A claims settlement waiting for a person, with each protection numbered where it applies on the task" -->
- **Human task · Approve a write: pay a claim settlement**: The claims agent wants to pay a repair shop. Nothing is paid until a reviewer decides.
- **Requested by**: Claims agent, in a chat with a claims handler
  - Nobody approves their own request, unless the team allows it.
- **Tool**: Pay settlement, in the claims system (a write)
- **Input**:
  ```json
  { "claim": "CLM-20931", "payee": "Harbor Auto Body", "amount": 2140.00 }
  ```
  - The approval is bound to this exact input. Changing one character after approving voids it, and an approval is good for 15 minutes.
- **Waiting**: 2 days, using no worker
  - A run can wait a minute or a week. A deadline that passes marks the task overdue and never approves it.
- **Actions**: Approve, Reject
  - Approve runs the write once, even if it is decided twice. Reject makes no change. Both keep who decided, when and why.

Here is when a task is opened, and who can open one:

- **Reads never wait.** An agent that only reads data is never paused. Until a team turns approvals on, writes run at
  once as well.
- **Workflows and other systems can ask too.** A workflow asks a person with a **Human review** step, or with an **Ask**
  step when it needs a free-text answer. Another system can open a task through the API and read the decision back.

## What a task looks like

Each task is drawn from a task type, which sets the question, the evidence, any fields to check and the actions a person
can take. Ops AI comes with five types. A builder can copy one to make a more specialised type, and no type needs code.

| Task type | Used for |
|---|---|
| Write approval | A tool call waiting to write: the input, the system and what approving does |
| Document check | Values read from a document, shown beside the page they came from, to correct or accept |
| Generic decision | A question with a few named actions |
| Acknowledgement | A person confirms they have seen something |
| Data entry | A form a person fills in before the run goes on |

## Settings that control approvals

| Setting | Where | What it does | Default |
|---|---|---|---|
| Ask before an agent changes anything in an app | Settings › Approvals | Writes wait for a person, for the whole team | Off |
| Per app | Settings › Approvals | A different answer for the apps you pick | The team setting |
| Per tool | The tool's page, **Access and approval** | A different answer for one tool; the most specific level wins | The app's setting |
| Who answers | Each level above | Don't ask, ask the person in the chat, or ask a reviewer with a role you choose | Don't ask |
| People can approve their own requests | Settings › Approvals | The person who asked may also decide | Off |
| Test runs on live accounts ask first | Settings › Approvals | A test run that has no sandbox account asks before each write | On |
| Step-up | Govern › Policies, or a tool's approval policy | The approver signs in again (within five minutes) before the decision counts | Off |
| Two approvers | A tool's approval policy | Two different people must approve; the same person twice is refused. Use it for anything that moves money | Off |
| Task assist | Govern › Policies | A model summarises the task and suggests an action, marked as AI | Off |

Whatever these settings say, every write an AI assistant makes over MCP waits for a person. Whether someone may decide
at all depends on their role's decide permission ([Teams and access](teams-and-access.md)).

## Current limits

- When a task is decided, Ops AI does not call the other system back, so a caller polls the task for its decision.
  Webhooks are planned.
- Deciding from buttons in email or Microsoft Teams is planned. Today, decisions are made in the console, in chat, with
  the command line or through the API.
- Resuming several pauses in one run with a single decision is planned.

## When approvals are working

An action that changes data waits as a task that shows the exact input. A reviewer approves or rejects it with a reason,
and the record keeps who decided and when. If they approve, the write runs once and the chat or workflow carries on. If
they reject it, nothing is written. So when your risk team asks who approved a change, you can point them to the task.

## Without a task

Without a task, the approval lives in an email thread or a chat message. That message does not say which input was
approved, so the write can run again with a different one. Each time someone asks for the audit trail, your team has
to rebuild the answer by hand.

## Next

<!-- site: cards -->
- **[Cases](cases.md)**: the record a task belongs to, and what it waits on.
- **[Workflows](workflows.md)**: add a human review step to a process.
- **[Teams and access](teams-and-access.md)**: who may decide.
- **[Tools and apps](apps.md)**: which tools write, and their approval settings.
