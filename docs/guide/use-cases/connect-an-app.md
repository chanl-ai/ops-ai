# Connect an app and use it in an agent

Status: current. Run end to end against a Salesforce stand-in, in the console, the API, the SDK and the CLI.

A service desk wants an agent that can look up a case in Salesforce and escalate it when asked, without handing the
agent a password and without an unseen change reaching the CRM. This guide turns the Salesforce app on, gives its tools
to an agent, and works a case in chat. The same steps fit any App.

## Before you start

| Who | Needs |
|---|---|
| A team admin | To turn the App on and sign in the team login |
| A builder | To add tools to an agent and publish it |
| A Salesforce user | Access to Ops AI's connected app in your org (see [Salesforce](../integrations/salesforce.md#if-sign-in-fails)) |

## Steps

<!-- site: steps -->
1. **Turn Salesforce on.** A team admin opens **Data Gateway › Apps**, presses **Turn on** on Salesforce, picks where
   the team signs in and whose account calls use, and keeps **Give the team's assistant this app's read tools** ticked.
   The window reads **Saved. Salesforce is on for** your team and how many read tools were added.
2. **Connect.** Press **Sign in the team login** and allow access on Salesforce's page. The App reads **Connected**.
3. **Try a tool.** On the App's **Tools** tab, open Run a query, enter `SELECT Id, CaseNumber, Status FROM Case LIMIT 1`
   and press **Run** in **Mock**: nothing leaves Ops AI. Then **Real**: you see your org's answer and the request sent,
   with the token hidden.
4. **Give the tools to an agent.** On the App's **Resources** tab, press **Add to team** on the case helper agent. Or
   open your own agent and add Run a query and Update a record under **Tools**. Publish.
5. **Ask in chat.** "What is the status of case 00044818?" The agent runs the query and shows the case.
6. **Ask it to change something.** "Escalate case 00044818." If your team asks before writes, a card names the tool,
   Update a record, and the change, Status: Escalated, and waits for a yes. Salesforce is unchanged until then.

Expected: after the approval, the case reads Escalated in Salesforce, changed by the account the App signed in with,
and the App's **Logs** tab lists both calls with who each ran as.

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
| Whose account calls use | The team's; each person's; each person's with the team's for runs nobody started | Asked when the App is first turned on |
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
