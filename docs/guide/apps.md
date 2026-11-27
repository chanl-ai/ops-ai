# Tools and apps

Status: current. Rows marked planned are designed and not built.

This page shows how your agents can look up a customer in the systems you already use and, once a person approves,
change a record there.

## Why agents need to reach your systems

Most of the work in an operations queue depends on data that lives in other systems. An operations team needs its agent
to look up the customer, read the account and, once someone approves, place the hold. A claims team needs the policy and
the open claim, and a lending team needs the loan balance before it can quote a payoff. If the agent can only hold a
conversation, the person still does every one of those steps by hand, and the queue stays as long as it was.

Connecting agents to your systems without any checks creates a different problem. Each agent would carry its own keys
and follow its own rules, nobody could say which account it signed in as, and a risk review would have no single place
to read what it changed.

Ops AI solves this with apps and tools. An app is a system outside Ops AI that your agents and workflows work with, such
as Salesforce, a core banking API or a mailbox. Each app brings a set of tools, and each tool is a single operation that
an agent or a workflow step can carry out in that app, such as "get account" or "place hold". Every tool call leaves
through one gateway, which checks who is calling, whether a person has approved the call, and which hosts it may reach.

## How it works

<!-- site: steps -->
1. **Turn an app on.** A team admin picks the app and chooses who signs in to it.
2. **Check what its tools do.** Each tool is marked read or write. You can run a tool against mock answers before it
   touches anything real.
3. **Decide which writes wait.** Tools that only read run straight away. A team admin can make tools that write wait for
   a person, either for the whole team, for chosen apps or for one tool.
4. **Give the tools to an agent.** The agent calls them in a chat or a workflow, and every call is recorded in the log.

## Try it

From the command line you can see which apps your team has turned on, what one of them can do, and call one of its
tools.

```bash
opsai apps list
opsai apps show <app-id>
opsai tools list --app <app-id>
opsai tools run <app-id> <tool> --input '{"accountId": "ACC-1001"}'
opsai tools run <app-id> <tool> --input '{"accountId": "ACC-1001"}' --real
```

By default, `tools run` replies from the tool's mock answers and sends nothing to the app. Adding `--real` sends the
call as a test run, and it passes through every check the gateway applies.

The console has the same views under **Data › Apps**, which lists the team's apps, and **Data › Tools**. On a tool's
page, **Run** offers two choices. **Mock** replies from the saved mock answers and sends nothing, while **Real** sends
the request and shows you exactly what was sent, with every key hidden.

## Turn an app on

<!-- site: steps -->
1. A team admin opens **Data › Apps**, view **Team setup**, and presses **Turn on** on the app's card.
2. They choose who signs in, either **Everyone uses the team's login** or **Each person signs in**. Saving this choice
   does not sign anyone in yet.
3. Pressing **Sign in with my login** or **Sign in the team login** opens the app's own sign-in page. Once a login has
   signed in, the app shows **Connected**.

[Set up an app](apps-setup.md) covers the full steps, the states an app can be in, how to bring your own OAuth app and
how to turn an app off.

## Who signs in: the team's login or each person's

For each app, a team admin decides whose login the tools use. The choice sits on the app's **Settings** tab under
**Who signs in**, and the agent's **Tools** list shows the same answer beside each tool's app.

<!-- site: compare caption="The two answers to who signs in to an app, and what the chat user and the audit see" -->
- **Everyone uses the team's login**: Suits a shared mailbox.
  - **Chat user sees**: No sign-in and no question. Under the reply: "Runs in `<app>` as `<login>` (team login). You are recorded as the person who asked."
  - **Audit keeps**: The team login and the person who asked
- **Each person signs in**: Suits a system that records who did what, such as a core banking API.
  - **Chat user sees**: The first time, one card: **Sign in to `<app>` to continue**. After signing in the chat carries on, and later actions in that app ask nothing
  - **Audit keeps**: The person's own login

Because the team admin makes this choice, nobody is asked in a chat or a Human Task to pick between their own login
and the team's. Each person manages their own sign-ins in **My apps**.

When an app is set so that each person signs in, a run that nobody started, such as a schedule, cannot call it. There is
no person for the run to act as, and the team's login is not used as a backup. Instead, the run is refused with a
message that names the app and the two ways forward: set the app to Everyone uses the team's login, or have a person
start the run. So that this does not surprise you later, saving a workflow that a schedule or an event starts warns you
about each such step before its first run. Changing the answer needs the `connections.manage` permission, which team
admins have by default.

| Login | Used by | How to add it |
|---|---|---|
| Team login | Anyone in the team. The **Default** account answers every live call that names no other | **Sign in the team login**, by a team admin |
| Your login | Tools you run, and agents acting for you | **Sign in to <app>** in a chat, or **My apps** |
| Sandbox account | Test runs only | **Add a sandbox account** on the app's page |

### Your own sign-ins

You manage your own sign-ins on **Apps › Mine**, which you can also reach as **My apps** in the user menu. It shows one
card for each app the team has turned on, with Connect, Reconnect or Add another account. If you have two accounts in
one app and neither is set as the default, the assistant asks you which one to use.

## What the gateway checks on every call

- **Accounts.** When an agent acts for a person, it uses that person's own account, so it can reach only what that
  person is allowed to reach.
- **Sandbox and live.** Test runs use an account marked Sandbox. Test runs include an agent's Test panel, a draft, and
  **Real** on a tool's page. Live runs never use a sandbox account. If an app has no sandbox account, a test run that
  writes asks the person before it goes ahead.
- **Reads and writes.** Every tool is marked read or write. Writes run straight away until a team turns approvals on.
  After that, each write waits as a Human Task ([Human tasks and approvals](human-tasks.md)).
- **Secrets.** Keys and passwords that a tool sends are stored encrypted and never shown again, and they are removed
  from whatever an app sends back. If you type a key into a tool's own header, saving the tool refuses it, because the
  app's account signs every call.
- **Allowed hosts.** A tool can call only the hosts that a Security admin has allowed.
- **Call log.** Every call is logged together with the account it ran as. An app's **Logs** tab shows its calls to the
  people who are allowed to read the log.

## Where tools come from

| Source | What you get | Status |
|---|---|---|
| A built-in or installed app | The app's tools, and sometimes resources: agents, skills, workflows and document types your team can copy | built |
| An OpenAPI 3.0 or 3.1 document | One tool per operation, reviewed before use | built |
| An MCP server | Its tools, through the same gateway | built |
| A tool written in the console | A request on an app's address, with mock answers for tests ([Build your first tool](build-your-first-tool.md)) | built |
| A Python function in a sandbox with no network, files or secrets | A code tool | partial: runs, writing one in the console is planned |

## Approvals

By default, a tool that writes runs straight away. A team admin can make writes wait for a person at three levels:

- the whole team
- the apps they pick
- one tool, on the tool's page under **Access and approval**

When more than one level is set, the most specific one applies. Each level has three settings: don't ask, ask the
person in the chat, or ask a reviewer. A write that waits becomes a Human Task
([Human tasks and approvals](human-tasks.md)).

## Assistants over MCP

An AI assistant such as Claude or Cursor can call your team's tools over MCP. These calls pass through the same
gateway as an agent's calls and count as test runs, so they use an app's sandbox account when the team has one.

| What the assistant reaches | Writes |
|---|---|
| The team's address lists the team's read tools only | None are listed |
| A link a builder made on **Channels › MCP** lists the tools and workflows picked for it, writes included | A write always waits for a person, whatever the team's approval settings say |

There is one exception. An operation that only creates a draft, such as installing a template or starting a
workflow, does not wait, because the draft still goes through its own review before it is published. Setup steps are
on [MCP](../reference/mcp.md).

## Who may do what

| Action | Who |
|---|---|
| Turn an app on or off, sign in its team login, set who signs in, add a custom app | A team admin |
| Connect, set as default or disconnect your own account | Anyone in the team |
| Add or edit an auth config (the OAuth app an app signs in with) | A team admin |
| Add, rotate or delete a secret | A Security admin |
| Change approval settings | People who manage the team's reviews |

## Limits

- Triggers that an app starts on a schedule or by polling, and signed incoming webhooks, are planned.
- The team's MCP address lists read tools only. To write over MCP, an assistant needs a link, and every write waits for
  a person.

## When your apps are set up well

Your team admin has turned on the apps the team uses, and each tool is marked read or write. An agent can read an
account without asking anyone, and a write waits for a person once the team has turned approvals on. Because the app's
**Logs** tab shows every call and the account it ran as, your risk review has one log to read.

## The risk of going without the gateway

Without the gateway, each agent would hold its own keys. A single leaked key would expose every agent.
A write could reach a customer's account with no person named against it, and finding out what an agent changed would
mean searching through each agent's logs one by one.

## Next

<!-- site: cards -->
- **[Set up an app](apps-setup.md)**: turn an app on, sign it in, bring your own OAuth app, turn it off.
- **[Build your first tool](build-your-first-tool.md)**: write a tool and test it against mock answers.
- **[Human tasks and approvals](human-tasks.md)**: make writes wait for a person.
- **[Install and turn on a plugin](plugins-install.md)**: add an app the catalog does not have.
