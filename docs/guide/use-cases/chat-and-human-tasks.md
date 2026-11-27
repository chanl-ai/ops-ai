# Start the day from chat

Status: current.

This guide shows you how to open the chat home, ask what needs you, and decide each waiting task without leaving the chat.

## Your morning is spread across several tools

If you work in operations, your morning is probably spread across several tools. Approvals sit in one queue, case
notes in another and the handbook in a third, and you still have to ask a colleague what happened to yesterday's run.
The approvals that block a customer wait the longest, because nobody knows they are waiting.

The chat home brings all of this into one place. You ask one question to see what needs you, and each answer is one
click from done. The same chat also answers questions from the handbook and follows up on a run for you.

## The plan

<!-- site: steps -->
1. **Sign in.** The chat home opens first, with four starting points under the message box: **What needs me today**,
   **Find a case**, **Start a workflow** (shown to people who may run workflows) and **What happened to a run**. When
   something is waiting for you, up to three hints from your own work take their place. They point to your
   longest-waiting Human Task, the case due soonest and your newest run in flight.
2. **Ask what needs you.** Press **What needs me today** (or the waiting-task hint), or type the question yourself. The
   assistant lists your Human Tasks as cards, oldest first, and each card has **Approve** and **Reject**.
3. **Decide in the chat.** A decision you make here goes through the same review as one made on the **Human Tasks**
   page, under the same rules. A payment asks you to sign in again before it approves, and a second approver is needed
   wherever the policy says so.
4. **Ask about the work.** You might ask, "What does the handbook say about debit disputes after 60 days?" Your
   team's agents answer from the knowledge bases they are given, and each answer cites the section it came from.
5. **Follow up on a run.** Press **What happened to a run** and name the run you mean. The assistant reads it and tells
   you where it is.

## Try it

Sign in and ask **What needs me today**. If a card is waiting, press **Approve** or **Reject**. If the list is empty,
start a task with [Card disputes](card-disputes.md) first so that you have something to decide.

![The chat home: Good morning, Maya; a message box; four starting points (What needs me today, Find a case, Start a workflow, What happened to a run); and your waiting work below](images/chat-home-light.png)

## What success looks like

You see every task that is waiting on you, each listed once. When you decide a task it leaves the list, and the
**Human Tasks** page shows the same decision with who made it and when. When you ask a question about policy, the
answer comes back with the section it came from.

## What skipping it costs

Without one place to start, an approval can sit in a queue that nobody has opened, and the customer behind it waits
too. When the approver finally gets to it, they decide from a queue instead of from the question that created the
task.

## What the assistant can see

The assistant acts as you, so it reads only what you may see in your team and can do only what you may do.

| You ask | It uses | Needs |
|---|---|---|
| What needs me today | Your Human Tasks | Nothing extra |
| Find a case | The team's cases | Permission to read cases |
| Start a workflow | The team's published workflows | Permission to run them |
| A question about policy | The knowledge bases the agent is given | The agent has the base |
| Something in an App, such as Salesforce | The App's tools, signed in as you or the team | The App is on, and you connected if it asks |

## Do it from code

The samples below list the Human Tasks waiting in a team and decide one, and they were run against a running install. The API calls these reviews, while the SDK
and the CLI call them tasks.

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

- The assistant can decide only the tasks you may decide. A task that needs a second approver stays open until that
  second person approves it.

## Next

<!-- site: cards -->
- [Hold a write for approval](approve-a-write.md): what makes a task wait for you.
- [Answer questions from your documents](answer-from-documents.md): give the agent a handbook to cite.
- [Chat](../ops-assistant.md): everything the chat can do.
