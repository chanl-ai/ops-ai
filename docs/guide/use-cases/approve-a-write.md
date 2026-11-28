# Have a person approve an agent's changes before they happen

Status: current.

You can let an agent change data in your apps and still have a person approve each change first. The approver sees
exactly what will change, and the change runs once, only after they approve it.

## Some actions need a person's approval

An agent can look up an account's balance straight away, because reading data changes nothing. Freezing the account
or escalating a case is different, and you want someone to see exactly what will change before it happens. If the
agent makes the change on its own, any mistake goes straight to the customer. If you collect the approval by email
instead, nobody can show later which input the approver actually saw.

When you turn on approvals, any action that changes data waits. The person in the chat, or a reviewer you choose,
sees the tool and every field it will change. The action runs once, and only after they approve it.

## The plan

<!-- site: steps -->
1. **Turn on approvals** for your whole team, for one app, or for a single tool.
2. **Choose who approves**: the person in the chat, or a reviewer with a role you pick.
3. **Ask the agent to change something.** Reading data still happens straight away, but the change waits on a card.
4. **Decide.** If you approve, the change runs once. If you deny it, nothing runs.

## Try it

In this walk-through you make every change in your team wait for approval, and then watch one wait. You need an
agent that has a tool able to change data. If you don't have one yet, [Connect an app to an agent](connect-an-app.md)
builds one.

<!-- site: steps -->
1. **Turn on approvals.** Your team admin opens **Settings › Approvals** and turns on **Ask before an agent changes
   anything in an app**.
2. **Choose who approves.** With **Ask the person**, the person in the chat confirms, and nobody else can. With **Ask a
   reviewer**, someone else who holds the role you choose approves it.
3. **Narrow it down if you need to.** Below the team switch, you can add an app and give it its own setting, for
   example Salesforce with Ask a reviewer. On a single tool's page, **Access and approval** sets the choice for that
   tool alone. When settings overlap, the most specific one wins.
4. **Ask the agent to change something.** In the chat, ask for a change. If you followed the connect guide, try
   "Escalate case 00044818." Reading data still happens straight away.
5. **See the card.** With Ask the person, the chat shows **Allow** and **Deny**, along with the tool's name and each
   field it will change. With Ask a reviewer, the change becomes a task in the reviewer's **Human Tasks** queue.
6. **Decide.** Choosing Allow, or a reviewer's Approve, runs the change exactly once. Deny runs nothing. If you choose
   **Allow for this chat**, the agent stops asking about that app for the rest of the chat.

## What success looks like

While the card waits, nothing reaches the app. Once someone approves, the app holds exactly one change, and the call
log shows it along with who approved it. If someone denies it, the app is unchanged and the record shows who
refused.

## What happens without approvals

With approvals turned off, an agent's changes go straight to the app. If the agent gets one wrong, it reaches the
app before anyone has had a chance to check it. Approvals kept in an email thread don't record which input was
approved either, so each time someone asks you for the audit trail, your team has to piece it together by hand.

![The Human Tasks queue: open, overdue and decided counts, then each request with its time left, status and risk](https://opsai.chanl.ai/docs/media/human-tasks-light.png)

## Decide from code

A reviewer can also decide tasks from a script. The script has to sign in as the reviewer, because an API key can't
decide a task.

```python tab="Python"
from ops_ai import OpsAI

reviewer = OpsAI(profile="reviewer")
for task in reviewer.tasks.list(view="open"):
    print(task["id"], task.get("question"))
reviewer.tasks.decide("wfrun_...", "approved", reason="Freeze confirmed with the branch.")
```

```bash tab="CLI"
opsai tasks list --view open
opsai tasks approve wfrun_... --reason "Freeze confirmed with the branch."
```

## The settings

| Setting | What it does | Default |
|---|---|---|
| Ask before an agent changes anything in an app | For the whole team, changes wait for the approver chosen below | Off, so changes run straight away |
| Who answers | Ask the person in the chat, or ask a reviewer with a role you choose | Ask the person |
| Per app | Use the team setting, don't ask, ask the person, or ask a reviewer | Use the team setting |
| Per tool (**Access and approval**) | The same choices, for one tool | Follows the app's setting, then the team's |
| Two-person rule | When on, the person who asked can't decide, so someone else approves. Team admins can still decide their own requests. When off, people can approve their own requests if their role allows it | Off |
| Test accounts never ask | Changes to an app's sandbox account run without asking | On |
| Test runs on live accounts ask first | A test run from a tool's page asks before it changes a live account | On |

Whether someone can approve at all depends on the approve permission in their role. The built-in Admin, Reviewer and
Builder roles all have it.

## How Ops AI decides whether a change waits

Three questions decide whether an action waits, and who is asked.

<!-- site: decision source caption="Whether a write waits, and who answers" -->
- **Does the call only read data?**
  - **Yes**: It runs straight away and is logged. Reading data never waits.
  - **No, it changes data**: What matters next is where the call came from.
    - **Did it come over MCP, from an outside AI client calling the tool?**
      - **Yes**: It waits for a person whatever the settings say, because nobody is in a chat to confirm it. The one exception is a change that only creates a draft.
      - **No, it came from a chat or a workflow**: Your settings decide.
        - **Are approvals on for this tool, this app or the team? The most specific setting wins.**
          - **Yes**: It waits. A workflow has no person in a chat, so Ask the person becomes Ask a reviewer.
          - **No**: It runs straight away and is logged with who asked.

If Ops AI can't read your team's approval settings, it refuses every change, so nothing in your apps changes.
Reading data still works.

## Next

<!-- site: cards -->
- [Card disputes](card-disputes.md): a workflow where a credit waits for an approver.
- [Start the day from chat](chat-and-human-tasks.md): deciding Human Tasks from the chat.
- [Security and governance](../security-and-governance.md): how approvals work as a control.
