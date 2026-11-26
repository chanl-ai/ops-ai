# Start the day from chat

Status: current. In the console today; the SDK calls below were run against a running install.

**Open the chat home, ask what needs you, and decide each waiting task where you stand.**

## Your morning is spread across several tools

An operations person's morning is spread across tools: approvals in one queue, case notes in another, the handbook in a
third, and a colleague to ask what happened to yesterday's run. The approvals that block a customer wait the longest,
because nobody knows they are waiting.

The chat home puts them in one place. One question lists what needs you, each answer is one click from done, and the
same chat answers questions from the handbook and follows up on a run.

## The plan

<!-- site: steps -->
1. **Sign in.** The chat home opens first. Under the message box sit four starting points: **What needs me today**,
   **Find a case**, **Start a workflow** (shown to people who may run workflows) and **What happened to a run**. When
   something is waiting, up to three hints from your own work replace them: your longest-waiting Human Task, the case
   due soonest and your newest run in flight.
2. **Ask what needs you.** Press **What needs me today** (or the waiting-task hint) or type it. The assistant lists your Human Tasks, oldest first,
   as cards with **Approve** and **Reject**.
3. **Decide in the chat.** A decision here goes through the same review as the **Human Tasks** page, with the same
   rules: a payment asks you to sign in again before it approves, and a second approver is needed where the policy says so.
4. **Ask about the work.** "What does the handbook say about debit disputes after 60 days?" A team's agents answer
   from the knowledge bases they are given, and cite the section each answer came from.
5. **Follow up on a run.** Press **What happened to a run** and name it. The assistant reads the run and says where it
   is.

## Try it

Sign in and ask **What needs me today**. If a card is waiting, press **Approve** or **Reject**. If the list is empty,
start a task with [Card disputes](card-disputes.md) first.

![The chat home: Good morning, Maya; a message box; four starting points (What needs me today, Find a case, Start a workflow, What happened to a run); and your waiting work below](images/chat-home-light.png)

## What success looks like

Every task waiting on you is listed once, a task you decide leaves the list, and the **Human Tasks** page shows the
same decision with who made it and when. A question about policy comes back with the section it came from.

## What skipping it costs

Without one place to start, an approval waits in a queue nobody opened and the customer behind it waits with it. The
approver then decides from a queue instead of from the question that made the task.

## What the assistant can see

The assistant acts as you. It reads only what you may see in your team, and it can do only what you may do.

| You ask | It uses | Needs |
|---|---|---|
| What needs me today | Your Human Tasks | Nothing extra |
| Find a case | The team's cases | Permission to read cases |
| Start a workflow | The team's published workflows | Permission to run them |
| A question about policy | The knowledge bases the agent is given | The agent has the base |
| Something in an App, such as Salesforce | The App's tools, signed in as you or the team | The App is on, and you connected if it asks |

## Do it from code

List the Human Tasks waiting in a team and decide one. The API calls them reviews; the SDK and CLI call them tasks.

```python tab="Python"
from ops_ai import OpsAI

ops = OpsAI(profile="reviewer")  # a signed-in person; an API key cannot list or decide tasks
for task in ops.tasks.list(view="open"):
    print(task["id"], task["status"], task.get("question"))
ops.tasks.decide("wfrun_...", "approved", reason="Checked against the handbook.")
```

```ts tab="TypeScript"
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ profile: 'reviewer' });  // a signed-in person; an API key cannot list or decide tasks
for await (const task of ops.tasks.list({ view: 'open' })) console.log(task.id, task.status, task.question);
await ops.tasks.decide('wfrun_...', 'approved', { reason: 'Checked against the handbook.' });
```

```bash tab="CLI"
opsai chat say -m "What needs me today?"
opsai tasks list --view open
opsai tasks approve wfrun_... --reason "Checked against the handbook."
```

## Limits

- The assistant decides only tasks you may decide. A task that needs a second approver stays open until one approves.

## Next

<!-- site: cards -->
- [Hold a write for approval](approve-a-write.md): what makes a task wait for you.
- [Answer questions from your documents](answer-from-documents.md): give the agent a handbook to cite.
- [Chat](../ops-assistant.md): everything the chat can do.
