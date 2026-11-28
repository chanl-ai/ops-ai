# Connect an app and use it in an agent

Status: current.

This guide shows you how to turn on an app, give its tools to an agent and work a real case in chat, without ever
handing the agent a password. Every step was run end to end against a Salesforce stand-in, in the console, the API,
the SDK and the CLI.

## Your agent needs to reach your CRM safely

Say your service desk wants an agent that can look up a case in Salesforce and escalate it when someone asks. The quick
route is to paste a password into the prompt, but that gives the agent more access than it should have and leaves no
record of what it did. It also lets a change nobody has seen reach the CRM, which is how a case gets escalated by
mistake.

An app avoids this because it holds the sign-in itself, so the agent never sees it. The agent gets only the tools you
add, and each call is logged with who it ran as. Any action that changes data can also wait for a person to approve
it. This guide uses Salesforce, but the same steps work for any app.

## What you'll do

<!-- site: steps -->
1. **Turn the app on** and sign in with the team login.
2. **Try a tool** in Mock first, then in Real.
3. **Give the tools to an agent** and publish it.
4. **Work a case in chat**, then ask for a change and approve it.

## Before you start

| Who | Needs |
|---|---|
| A team admin | To turn the app on and sign in the team login |
| A builder | To add tools to an agent and publish it |
| A Salesforce org with a case in it | Without one, follow [Build your first tool](../build-your-first-tool.md) with an app you have |
| A Salesforce user | Access to Ops AI's connected app in your org (see [Salesforce](../integrations/salesforce.md#if-sign-in-fails)) |

## Try it

<!-- site: steps -->
1. **Turn Salesforce on.** A team admin opens **Data Gateway › Apps**, presses **Turn on** on Salesforce, picks whether everyone uses the team's login or each person signs in, and keeps **Give the team's assistant this app's read tools** ticked.
   The window reads **Saved. Salesforce is on for** your team and how many read tools were added.
2. **Connect.** Press **Sign in the team login** and allow access on Salesforce's page. The app reads **Connected**.
3. **Try a tool.** On the app's **Tools** tab, open Run a SOQL query, enter `SELECT Id, CaseNumber, Status FROM Case LIMIT 1`
   and press **Run** in **Mock**. In Mock, nothing leaves Ops AI. Then switch to **Real** and run it again, and you
   see your org's answer and the request that was sent, with the token hidden.
4. **Give the tools to an agent.** On the app's **Resources** tab, press **Add to team** on the Case helper agent, on the app's **Agents** tab. If
   you would rather use your own agent, open it, add Run a SOQL query and Update a record under **Tools**, and publish it.
5. **Ask in chat.** Type "What is the status of case 00044818?" and the agent runs the query and shows you the case.
6. **Ask it to change something.** An action that changes data runs straight away unless approvals are turned on, so
   first turn them on under **Settings › Approvals** ([Hold a write for approval](approve-a-write.md)). Then ask
   "Escalate case 00044818." A card appears and waits until someone approves it.

## What you should see

Until someone approves the change, Salesforce stays as it was. Once they approve it, the case is escalated and the
app's log shows both calls.

<!-- site: journey caption="Escalating a case from chat, where nothing changes in Salesforce until a person approves it" -->
1. **Chat · Ask about the case**: The agent runs the query and shows the case.
   - **Question**: What is the status of case 00044818?
2. **Chat · Ask for a change**: A card names the tool and the change, and waits for someone to approve it. Until then, Salesforce stays as it was.
   - **Tool**: Update a record
   - **Change**: Status: Escalated
   - **Actions**: Approve, Reject
3. **Salesforce · The case after the approval**: The change was made by the account the app signed in with.
   - **Status**: Escalated
4. **Salesforce · Logs tab**: Both calls are listed, each with who it ran as.
   - **Calls**: Run a SOQL query, Update a record
   - **Ran as**: The account the app signed in with

## What happens without an app

Without an app, the agent cannot look at the case at all. If you give it a pasted password instead, it can do anything
that password allows, and nothing in Ops AI records which person asked or what the agent did.

## From the CLI

```bash
opsai apps on plugin:opsai.salesforce --whose team   # prints the sign-in link
opsai apps show plugin:opsai.salesforce              # card, accounts, tools and latest calls
opsai tools list --app plugin:opsai.salesforce      # each tool, read or write, and whether it is added
opsai chat say --agent "Case helper" -m "What is the status of case 00044818?"
```

## Choices along the way

| Choice | Options | Default |
|---|---|---|
| Who signs in | Everyone uses the team's login; Each person signs in | Asked when the app is first turned on |
| Give the assistant the read tools | On or off, when turning the app on | On |
| Actions that change data wait for a person | Don't ask, ask the person in the chat, ask a reviewer; per team, app or tool | Don't ask |
| Which tools the team uses | Each tool on or off on the app's **Tools** tab | All on |
| Test runs | A sandbox account answers them, live runs never do | The live account, asking before each write |

## Limits

- An agent cannot switch to a different account on its own. If the app has two accounts and no default, the agent
  asks the person which one to use.
- Turning an app off stops its tools for every agent and workflow in the team. Before you confirm, the window lists
  the ones that will stop.

## Next

<!-- site: cards -->
- [Hold a write for approval](approve-a-write.md): make the escalation wait for a reviewer.
- [Integrations](../integrations/overview.md): every app and sign-in kind.
- [Apps](../apps.md): accounts, auth configs and states.
