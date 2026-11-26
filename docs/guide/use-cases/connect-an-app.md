# Connect an app and use it in an agent

Status: current. Run end to end against a Salesforce stand-in, in the console, the API, the SDK and the CLI.

**Turn an App on, give its tools to an agent, and work a real case in chat, without handing the agent a password.**

## The agent needs your CRM, and no one should hand it a password

A service desk wants an agent that can look up a case in Salesforce and escalate it when asked. Pasting a password into a
prompt gives the agent more than it should have and leaves no record of what it did, and an unseen change reaching the
CRM is how a case gets escalated by mistake.

An App holds the sign-in, so the agent never sees it. The agent gets only the tools you add, each call is logged with
who it ran as, and a write can wait for a person. This guide uses Salesforce; the same steps fit any App.

## The plan

<!-- site: steps -->
1. **Turn the App on** and sign in the team login.
2. **Try a tool** in Mock, then Real.
3. **Give the tools to an agent** and publish it.
4. **Work a case in chat**, then ask for a change and approve it.

## Before you start

| Who | Needs |
|---|---|
| A team admin | To turn the App on and sign in the team login |
| A builder | To add tools to an agent and publish it |
| A Salesforce org with a case in it | Without one, follow [Build your first tool](../build-your-first-tool.md) with an App you have |
| A Salesforce user | Access to Ops AI's connected app in your org (see [Salesforce](../integrations/salesforce.md#if-sign-in-fails)) |

## Try it

<!-- site: steps -->
1. **Turn Salesforce on.** A team admin opens **Data Gateway › Apps**, presses **Turn on** on Salesforce, picks whether everyone uses the team's login or each person signs in, and keeps **Give the team's assistant this app's read tools** ticked.
   The window reads **Saved. Salesforce is on for** your team and how many read tools were added.
2. **Connect.** Press **Sign in the team login** and allow access on Salesforce's page. The App reads **Connected**.
3. **Try a tool.** On the App's **Tools** tab, open Run a SOQL query, enter `SELECT Id, CaseNumber, Status FROM Case LIMIT 1`
   and press **Run** in **Mock**: nothing leaves Ops AI. Then **Real**: you see your org's answer and the request sent,
   with the token hidden.
4. **Give the tools to an agent.** On the App's **Resources** tab, press **Add to team** on the Case helper agent, on the App's **Agents** tab. Or
   open your own agent and add Run a SOQL query and Update a record under **Tools**. Publish.
5. **Ask in chat.** "What is the status of case 00044818?" The agent runs the query and shows the case.
6. **Ask it to change something.** Writes run at once unless asking is on, so first turn it on under
   **Settings › Approvals** ([Hold a write for approval](approve-a-write.md)). Then "Escalate case 00044818." A card names the tool,
   Update a record, and the change, Status: Escalated, and waits for a yes. Salesforce is unchanged until then.

## What success looks like

After the approval, the case reads Escalated in Salesforce, changed by the account the App signed in with, and the
App's **Logs** tab lists both calls with who each ran as. Before the approval Salesforce is unchanged.

## What skipping it costs

An agent without an App cannot look at the case at all. An agent given a pasted password can do anything that
password allows, and nothing in Ops AI records which person asked or what the agent did.

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
| Who signs in | Everyone uses the team's login; Each person signs in | Asked when the App is first turned on |
| Give the assistant the read tools | On or off, when turning the App on | On |
| Writes wait for a person | Don't ask, ask the person in the chat, ask a reviewer; per team, App or Tool | Don't ask |
| Which tools the team uses | Each tool on or off on the App's **Tools** tab | All on |
| Test runs | A sandbox account answers them, live runs never do | The live account, asking before each write |

## Limits

- An agent cannot pick a different account by itself. With two accounts and no default, it asks the person which to
  use.
- Turning an App off stops its tools for every agent and workflow in the team; the window lists them first.

## Next

<!-- site: cards -->
- [Hold a write for approval](approve-a-write.md): make the escalation wait for a reviewer.
- [Integrations](../integrations/overview.md): every App and sign-in kind.
- [Apps](../apps.md): accounts, auth configs and states.
