# Tools and apps

Status: current. Rows marked planned are designed and not built.

An agent that can only talk is of little use to an operations team: it needs to look up the customer, read the account
and, with a person's approval, change something. An app is a system outside Ops AI that agents and workflows work with,
such as Salesforce, a core banking API or a mailbox. Each app brings tools: the single operations an agent or a workflow
step can take with it, such as "get account" or "place hold". Every tool call leaves through one gateway that checks who
is calling, the approval, and which hosts may be reached.

## Try it

See which apps your team has on, what one of them can do, and call one of its tools.

```bash
opsai apps list
opsai apps show <app-id>
opsai tools list --app <app-id>
opsai tools run <app-id> <tool> --input '{"accountId": "ACC-1001"}'
opsai tools run <app-id> <tool> --input '{"accountId": "ACC-1001"}' --real
```

`tools run` answers from the tool's mock answers and sends nothing; `--real` sends the call as a test run, through every
check. In the console the same views are **Data › Apps** (the team's apps) and **Data ›
Tools**. A tool's page has **Run** with **Mock**, which answers from saved mock answers and sends nothing, and
**Real**, which sends the request and shows exactly what was sent, with every key hidden.

## How it works

- **Accounts.** An app signs in with an account: the team's, or each person's own. A person's own account is used for
  the tools they run and for agents acting for them, so an agent reaches only what that person may reach.
- **Sandbox and live.** An account marked Sandbox is used by test runs (an agent's Test panel, a draft, **Real** on a
  tool's page). Live runs never use it. Without a sandbox account, a test run that writes asks the person first.
- **Reads and writes.** Every tool is marked read or write. Writes run at once until a team turns approvals on; then a
  write waits as a Human Task ([Human tasks and approvals](human-tasks.md)). Every write made over MCP waits for a
  person.
- **Secrets.** Keys and passwords a tool sends are stored encrypted, never shown again, and removed from whatever an app
  answers. A key typed into a tool's own header is refused when you save it: the app's account signs every call.
- **Allowed hosts.** A tool may call only hosts a Security admin has allowed.
- **Call log.** Every call is logged with who it ran as. An app's **Logs** tab shows its calls to people who may read
  the log.

## Where tools come from

| Source | What you get | Status |
|---|---|---|
| A built-in or installed app | The app's tools, and sometimes resources: agents, skills, workflows and document types your team can copy | built |
| An OpenAPI 3.0 or 3.1 document | One tool per operation, reviewed before use | built |
| An MCP server | Its tools, through the same gateway | built |
| A tool written in the console | A request on an app's address, with mock answers for tests ([Build your first tool](build-your-first-tool.md)) | built |
| A Python function in a sandbox with no network, files or secrets | A code tool | partial: runs, writing one in the console is planned |

## Who signs in: the team's login or each person's

A team admin answers one question per app, on the app's **Settings** tab under **Who signs in**. The agent's **Tools**
list shows the same answer beside each tool's app.

| Answer | What a chat user sees | What the audit keeps |
|---|---|---|
| **Everyone uses the team's login** | No sign-in and no question. Under the reply: "Runs in <app> as <login> (team login). You are recorded as the person who asked." | The team login and the person who asked |
| **Each person signs in** | The first time, one card: **Sign in to <app> to continue**. After signing in the chat carries on, and later actions in that app ask nothing | The person's own login |

Nobody is asked in a chat or a Human Task to choose between their own login and the team's. Each person manages their
own sign-ins in **My apps**. On an app each person signs in to, a run nobody started, such as a schedule, cannot call
it: there is no person to act as, and the team's login is not used as a backup. The run is refused with a message naming the app and the two ways on (set it to Everyone uses the team's login, or have a person start the run), and saving a workflow that a schedule or an event starts warns about each such step before its first run. Changing the answer takes the `connections.manage` permission (team admins by default).

| Login | Used by | How to add it |
|---|---|---|
| Team login | Anyone in the team. The **Default** account answers every live call that names no other | **Sign in the team login**, by a team admin |
| Your login | Tools you run, and agents acting for you | **Sign in to <app>** in a chat, or **My apps** |
| Sandbox account | Test runs only | **Add a sandbox account** on the app's page |

### Your own sign-ins

Each person's sign-ins are on **Apps › Mine** (also **My apps** in the user menu): one card per app the team turned on,
with Connect, Reconnect or Add another account. With two accounts of one app and no default, the assistant asks which to
use.

## Turn an app on

<!-- site: steps -->
1. A team admin opens **Data › Apps**, view **Team setup**, and presses **Turn on** on the app's card.
2. They pick who signs in: **Everyone uses the team's login** or **Each person signs in**. Saving signs nobody in.
3. **Sign in with my login** or **Sign in the team login** opens the app's own sign-in page. The app reads
   **Connected** once a login has signed in.

The full steps, an app's states, bringing your own OAuth app and turning an app off are on [Set up an app](apps-setup.md).

## Approvals

A write runs at once by default. A team admin makes writes wait for a person at three levels, and the most specific
level that is set wins: the whole team, the apps they pick, or one tool on its page under **Access and approval**. Each
level answers don't ask, ask the person in the chat, or ask a reviewer. A waiting write becomes a Human Task
([Human tasks and approvals](human-tasks.md)).

## Who may do what

| Action | Who |
|---|---|
| Turn an app on or off, sign in its team login, set who signs in, add a custom app | A team admin |
| Connect, set as default or disconnect your own account | Anyone in the team |
| Add or edit an auth config (the OAuth app an app signs in with) | A team admin |
| Add, rotate or delete a secret | A Security admin |
| Change approval settings | People who manage the team's reviews |

## Limits

- A scheduled or polled trigger from an app, and signed incoming webhooks, are planned.
- AI assistants calling the team's tools over MCP get read tools only, as test runs.

## Next

<!-- site: cards -->
- **[Set up an app](apps-setup.md)**: turn an app on, sign it in, bring your own OAuth app, turn it off.
- **[Build your first tool](build-your-first-tool.md)**: write a tool and test it against mock answers.
- **[Human tasks and approvals](human-tasks.md)**: make writes wait for a person.
- **[Install and turn on a plugin](plugins-install.md)**: add an app the catalog does not have.
