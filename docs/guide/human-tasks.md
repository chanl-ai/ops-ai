# Human tasks and approvals

Status: current. Rows marked planned are designed and not built.

**Pause the agent or workflow at the steps that matter, show a person exactly what will happen, and carry on only with
their decision.**

## Some steps need a named person on the record

A payment, a hold on an account, a reply to a customer, a field read from a blurry scan: none of these should happen
until a person has looked. If the agent simply runs, the first wrong write reaches a customer's account. If a person is
asked by email, nobody can later show what they were looking at when they said yes. A reviewer who signs off on a
summary cannot say what the agent was about to send.

A human task pauses the agent or workflow at that step, shows a person exactly what will happen, and carries on only
with their decision. Use it wherever your process needs a named person on the record: a claims team approving a
settlement, a lender confirming a payoff quote, a support team checking a refund.

## The plan

<!-- site: steps -->
1. **Choose which writes wait.** A team admin picks the whole team, some apps or one tool, and who answers.
2. **The agent asks.** When it reaches a write, the run pauses and a task shows the exact input.
3. **A person decides.** They approve or reject with a reason, in the console, in the chat or with the command line.
4. **The run carries on.** An approved write runs once. A rejected one makes no change. Either way the record keeps who
   decided, when and why.

## Try it

Make every write in your team wait for a person, then approve one.

<!-- site: steps -->
1. **Turn on approvals.** In the console open **Settings › Approvals**, turn on **Ask before an agent changes anything in
   an app**, set **Who answers** to **Ask a reviewer**, and pick the role that reviews.
2. **Ask for a write.** You need an agent that holds a write tool from an app your team has turned on
   ([Tools and apps](apps.md)). In a chat, ask it to do something, for example "Add a note to case 1042
   saying the customer called." The chat shows an approval card with the exact input and no write is made.
3. **Decide it.** A reviewer opens **Work › Human Tasks**, or uses the command line:

   ```bash
   opsai tasks list --view open
   opsai tasks show <task-id>
   opsai tasks approve <task-id> --reason "Checked with the customer"
   ```

   The write runs once, and the chat carries on with its result. `opsai tasks decide <task-id> reject --reason "..."`
   rejects it, and no write is made.

## What the person is protected by

A decision is tied to what the reviewer saw, and it counts once.

```mermaid caption="What happens to a write that waits for a person: it runs once if approved in time, and never runs on a timeout"
flowchart TD
  A[Agent reaches a write] --> B[Run pauses, using no worker]
  B --> C[Task shows the exact input]
  C --> D{Person decides}
  D -->|Approve| E[Write runs once]
  D -->|Reject| F[No change made]
```

A run can wait a minute or a week. An approval is good for 15 minutes, and changing one character of the input after it
voids it. A deadline that passes marks the task overdue and never approves it. Deciding twice resumes the run once.

- **Reads never wait.** Writes run at once until a team turns approvals on.
- **Nobody approves their own request**, unless the team allows it.
- **Workflows and other systems can ask too.** A workflow asks a person with a **Human review** step, or an **Ask** step
  for a free-text answer. Another system can open a task through the API and read the decision back.

## What a task looks like

Each task is drawn from a task type: the question, the evidence, any fields to check, and the actions a person can take.
Five types come with Ops AI; a builder copies one to make a specialised type, and no type needs code.

| Task type | Used for |
|---|---|
| Write approval | A tool call waiting to write: the input, the system and what approving does |
| Document check | Values read from a document, shown beside the page they came from, to correct or accept |
| Generic decision | A question with a few named actions |
| Acknowledgement | A person confirms they have seen something |
| Data entry | A form a person fills in before the run goes on |

## Options

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

Every write an AI assistant makes over MCP waits for a person, whatever these settings say. Who may decide at all is the role's decide
permission ([Teams and access](teams-and-access.md)).

## Limits

- Ops AI does not call another system when a task is decided. A caller polls the task for its decision. Webhooks are
  planned.
- Deciding from email or Microsoft Teams buttons is planned. Decisions are made in the console, in chat, with the
  command line or through the API.
- Several pauses in one run resumed as one decision is planned.

## What success looks like

A write waits as a task showing the exact input. A reviewer approves or rejects it, with a reason, and the record keeps
who decided and when. On approval the write runs once and the chat or workflow carries on. On rejection no write is
made. When the risk team asks who approved a change, the answer is on the task.

## What skipping it costs

Without a task, the approval lives in an email thread or a chat message. It does not say which input was approved, and
the write can run again with a different one. The audit answer is rebuilt by hand each time someone asks.

## Next

<!-- site: cards -->
- **[Cases](cases.md)**: the record a task belongs to, and what it waits on.
- **[Workflows](workflows.md)**: add a human review step to a process.
- **[Teams and access](teams-and-access.md)**: who may decide.
- **[Tools and apps](apps.md)**: which tools write, and their approval settings.
