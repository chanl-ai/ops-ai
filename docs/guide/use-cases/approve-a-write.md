# Hold a write for a person's approval

Status: current. Run end to end through the API, the SDK and the chat.

**Make an agent's writes wait for a person who can see exactly what will change, and run once only after a yes.**

## An agent that can write can write the wrong thing

An agent may read an account's balance at once, but freezing the account or escalating a case should wait for a person
who can see exactly what will change. If the write simply runs, the first wrong one reaches a customer. If a person is
asked by email, nobody can later show which input they approved.

An approval setting makes a write wait. The person in the chat, or a reviewer, sees the tool and each field it changes,
and the write runs once, only after a yes.

## The plan

<!-- site: steps -->
1. **Turn asking on** for the team, an App or one Tool.
2. **Choose who answers**: the person in the chat, or a reviewer with a role you pick.
3. **Ask the agent to change something.** Reads still run at once; the write waits as a card.
4. **Decide.** A yes runs the write once. A no runs nothing.

## Try it

Make every write in your team wait, then watch one wait. You need an agent that holds a write tool; [Connect an app
to an agent](connect-an-app.md) builds one.

<!-- site: steps -->
1. **Turn asking on.** A team admin opens **Settings › Approvals** and turns on **Ask before an agent changes anything in
   an app**.
2. **Pick who answers.** **Ask the person**: the person in the chat confirms, and only they can. **Ask a reviewer**:
   someone else with the role you choose approves.
3. **Narrow it if you need to.** Below the team switch, add an App and give it its own answer, such as Salesforce:
   ask a reviewer. On a single Tool's page, **Access and approval** sets that Tool's answer. The most specific one wins.
4. **Ask the agent to change something.** In chat, ask for a write, for example "Escalate case 00044818." if you followed the connect guide. Reads still run
   at once.
5. **See the card.** With Ask the person, the chat shows **Allow** and **Deny**, naming the tool and each field it
   changes. With Ask a reviewer, the write becomes a Human Task in the reviewer's queue.
6. **Decide.** Allow, or a reviewer's Approve, runs the write exactly once. Deny runs nothing. **Allow for this chat**
   stops the asking for that App in this chat.

## What success looks like

Nothing reaches the app while the card waits. After the yes, the app holds exactly one change, and the call log shows
the write with who approved it. After a no, the app is unchanged and the record shows who refused.

## What skipping it costs

With asking off, the first wrong write from an agent reaches the app. An approval kept in an email thread does not say
which input was approved, and the audit answer is rebuilt by hand each time someone asks.

![The Human Tasks queue: open, overdue and decided counts, then each request with its time left, status and risk](../../media/human-tasks-light.png)

## Decide from code

A reviewer can decide from a script, signed in as themselves. An API key never decides a task.

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
| Ask before an agent changes anything in an app | Team-wide: writes wait for the answer below | Off: writes run at once |
| Who answers | Ask the person, or ask a reviewer of a chosen role | Ask the person |
| Per App | Use the team setting, don't ask, ask the person, or ask a reviewer | Use the team setting |
| Per Tool (**Access and approval**) | The same choices for one Tool | Follows the App, then the team |
| Two-person rule | On: whoever asked cannot decide, so someone else approves; Admins of the team still decide their own requests. Off: people approve their own requests where their role lets them | Off |
| Test accounts never ask | A write on an App's sandbox account runs without asking | On |
| Test runs on live accounts ask first | A test run from a Tool's page asks before writing to a live account | On |

Who may approve at all is the approve permission on a role, held by the built-in Admin, Reviewer and Builder roles.

## Rules that always hold

Three checks decide whether a write waits.

<!-- site: decision source caption="Whether a write waits, and who answers" -->
- **Does the call only read?**
  - **Yes**: It runs at once and is logged. A read never waits.
  - **No, it writes**: The route it came by matters next.
    - **Did it arrive over MCP, an outside AI client calling the tool?**
      - **Yes**: It waits for a person whatever the settings say, since nobody is in the chat to confirm. The one exception is a write that only makes a draft.
      - **No, from a chat or a workflow**: The settings decide.
        - **Is asking on for this Tool, App or team? The most specific wins.**
          - **Yes**: It waits. In a workflow there is no person in a chat, so Ask the person becomes Ask a reviewer.
          - **No**: It runs at once and is logged with who asked.

If the team's approval settings cannot be read, every write is refused and none runs; reads still run.

## Next

<!-- site: cards -->
- [Card disputes](card-disputes.md): a workflow whose credit waits for an approver.
- [Start the day from chat](chat-and-human-tasks.md): deciding Human Tasks from chat.
- [Security and governance](../security-and-governance.md): approvals as a control.
