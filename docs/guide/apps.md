# Apps

Status: current. How a team turns on the Apps its agents and workflows use, signs in to them, and controls what their
Tools may do.

An App is something outside Ops AI that your agents and workflows work with. Each App brings Tools, the actions an agent
or a workflow step can take with it, and some also bring Resources: agents, skills, workflows and document types your
team can add as its own copies. An App signs in with an Account: the team's, or a person's own.

## The Apps menu

Open **Data Hub › Apps** in the sidebar. Four tabs sit at the top of every page in the menu.

| Tab | What it holds |
|---|---|
| Apps | Every App your team can use. Search by name, and narrow the list with **Connected only** or **Available only**. Built in Apps, such as Files and Document types, are always on and tagged **Built in** |
| Credentials | **App credentials**, the OAuth apps your Apps sign in with, and **Secrets**, the values Tools send, such as API keys |
| My accounts | The Apps you connected with your own Account. Disconnect one here |
| Tools | Every Tool your team can use, and **Tool calls**, the log of every call they made |

**Add custom app** on the Apps tab adds an App the catalog does not list: its address and the key or sign-in it uses.

## An App's state

Every App card, on the Apps tab and at the top of the App's page, shows one state. The App's Settings read the same
state, and each state has one next action.

| State (`appState` in the API) | When | What a team admin does | What a member sees |
|---|---|---|---|
| Connected (`connected`) | On, and its Account signed in | Nothing to do | Nothing to do |
| Signed in, test failed (`test_failed`) | On; the test after the sign-in failed | **Reconnect** | The failure |
| Needs sign-in (`needs_sign_in`) | On; the team's Account, or your own on an App each person signs in to, has not signed in | **Connect** | **Sign in from Mine** |
| Needs an auth config (`needs_auth_config`) | The App signs in through an auth config and the team has none it can use, or the one its Account used is gone or has no client secret | **Add an auth config**, which opens the new auth config for that App and signs nobody in | Ask an admin |
| Available (`off`) | Installed, and not on for the team: never turned on, or turned off | **Turn on** | Ask an admin |
| Not installed (`not_installed`) | The system does not hold this App's plugin and the team never had it on | Nothing; the operator installs Apps | The same |
| No longer installed (`removed`) | The team had it on; the system no longer holds its plugin | **Delete app** removes what it left | The same |

Before 9 November 2026 the API answered `not_installed` for an App that was installed and off for the team; that
state is now `off`, and `not_installed` means the plugin itself is missing. Code that reads `appState` from the SDK
should match `off` where it matched `not_installed`.

## Turn an App on

Turning an App on for the team and connecting an account are two separate actions. Turning it on saves the team's
setting and opens no sign-in; connecting is its own button, and it is optional for the admin who turned the App on.

| Step | What happens |
|---|---|
| 1. On **Connectors › Team setup**, press **Turn on** on the App's card (the App's page has the same button) | The Turn on window opens |
| 2. For an App that asks where you sign in (Salesforce), pick the place: login.salesforce.com, test.salesforce.com, or your company's address (My Domain), typed as its host | Saved on the App's auth config |
| 3. Pick whose account Tools use: each person's, the team's, or each person's with the team's for runs nobody started | Asked once, when the App is first turned on |
| 4. Keep **Give the team's assistant this app's read tools** ticked, or untick it | The assistant gets the read Tools when the App is saved |
| 5. Press **Turn on** | The team's setting is saved and no sign-in window opens. The window reads, for example, **Saved. Salesforce is on for Operations**, how many read Tools were added, and **Members connect their own account from Connectors › Mine** |
| 6. Optional: press **Connect my account**, or **Connect the team account** when Tools run as the team's account | The App's own sign-in page opens; allow access there, and the window names the account that signed in |

An App is **Connected** only once an Account has signed in or a test has passed; saving settings alone does not count.
The same rule holds everywhere an App's settings are saved: **Settings › Set up**, a new auth config and the Turn on
window each save and stop, and never start a sign-in. A sign-in starts only from a button that says Connect or Sign
in: **Connect** on the App's page once it is on, **Sign in** on an Account's row, or **Connect** on **Connectors › Mine**.

A member who opens an App the team has not turned on, from **Connectors › Mine**, reads **Not set up for your team
yet** with the admins to ask, and stays on Mine. Only someone who may turn the App on is offered **Turn on**, which
opens the App's page.

**Add account** works on an App with no Account yet: the first Account becomes the default. A team admin turns an App
on and connects the team's Accounts.

### The first time a team turns on a plugin's App

An App a plugin brings ([plugins guide](plugins.md)) needs two things before its card offers Connect, and its first
Connect window asks for more than the steps above.

| Who | What | Where |
|---|---|---|
| Platform admin | Installs the plugin (its folder in the plugins folder, or pinned in the image); it is then offered to every team. Settings fixed for every team come from the install config | `OPS_PLUGINS_DIR`, `deploy/plugins.json`, `OPS_PLUGIN_LOCKED` |
| Security admin | Lists the App's hosts, so its sign-in and calls may leave | **Settings › Security › Egress**, Add host (and Add range for a host on a private network) |
| Team admin | Presses **Turn on** | The window shows the App's settings (such as its API address), whose account calls use (the team's, each person's, or each person's with the team's as backup), the OAuth app (Ops AI's, or your own with its client ID and secret and the return address to register), and its sign-in address. **Turn on** saves them and opens no sign-in; **Connect my account** or **Connect the team account** after it opens the App's sign-in page |

The App's page is **Data Hub › Apps** then the App's name, at `/integrations/apps/plugin:<plugin id>`. One Connect is
enough to use it everywhere: test runs and live runs both sign in with the account you connected.

## Accounts: the team's and your own

The App's page lists its Accounts.

| Account | What it is |
|---|---|
| Team account | Anyone in the team can run Tools as it. The **Default** Account answers every live call that names no other |
| Your account | Your own sign-in. Tools you run, and agents acting for you, use it. Press **Connect my account** to add it |
| Sandbox account | Marked **Sandbox**. Test runs use it: an agent's Test panel, a draft, and **Real** on a Tool's page. Live runs never do. Press **Add a sandbox account** to add one, for example a Salesforce sandbox org |

Without a sandbox account, a test run signs in with the live account. It can read, but every write it makes waits for
a person to approve it first, so testing never changes live data unseen.

- **Add account** on an auth config adds a second Account of the same App, under its own name, for example a second
  region. It starts from where the default Account signs in. A step or a call names it to use it.
- **Make my default** makes one Account the one your own calls use when they name none.
- An Account the App stopped accepting reads **Expired** with **Reconnect**. Reconnect opens the App's sign-in page
  again; nothing is typed into Ops AI.
- On the App's **Settings**, **Everyone signs in with their own account** decides whether each person connects their own
  Account. Off, every call runs as the team Account.

## Connectors

**Connectors** in the sidebar shows your own sign-ins.

| Page | What it holds |
|---|---|
| My connectors | One card for each App your team turned on: what it can do, who it signs in as, and one action (Connect, Reconnect or Add another account). An App your team has off still has a card, with **Ask an admin** |
| Team setup | The admin view of the same Apps. Admins change setup here; members see it read-only |

- **Add another account** signs in through the same setup, so a personal and an office login sit side by side. Signing in
  again as a login already linked updates that account and says **Already connected as ...**.
- With two accounts of one App and no default, the assistant asks which to use. See
  [The Ops Assistant](ops-assistant.md).
- In a chat, the connector picker narrows which Apps that chat may use, before its first message.

## Auth configs and Secrets

An App's **Auth configs** tab, and **Auth configs** in the sidebar, list the OAuth app each App signs in with: **Ops AI**,
kept by Ops AI, or your team's own app. To bring your own app (a Salesforce connected app, a GitHub OAuth app):

| Step | Where |
|---|---|
| 1. Copy the **Callback URL** Ops AI shows | **New auth config**, **Edit**, and the auth config's row on the App's page |
| 2. Register it as the callback URL of your app at the system | Salesforce: the connected app's Callback URL. GitHub: the OAuth app's Authorization callback URL |
| 3. Enter the app's client ID and secret in Ops AI | **New auth config** or **Edit**; the secret is sealed and only its last four characters are shown |

A Salesforce app needs the **Manage user data via APIs (api)** and **Perform requests at any time (refresh_token,
offline_access)** scopes; without the second, people are signed out when the first token ends.

Ops AI builds the callback URL from its console address (`OPS_CONSOLE_URL`), so it must match the address people open.
Changing the client ID or permissions makes the accounts on it sign in again.

**Credentials › Secrets** lists the values Tools send, such as an API key in a header. A value is encrypted, never shown
again, and removed from whatever an App answers. A Security admin adds, rotates and deletes Secrets.

## Tools

The App's **Tools** tab lists the Tools it brings by their titles. The Apps menu's **Tools** tab lists every Tool of the
team, and **New tool** makes one of your own:

1. Name it and pick the App it calls. The App gives the address and the sign-in, so each request is a path on the App,
   such as `/accounts/{id}`.
2. Write the request on the Tool's page and press **Run** in **Mock**: it answers from the Tool's mock answers and sends
   nothing.
3. Once the Tool is published, **Real** sends the request as a test run, through the App's sandbox account when it has
   one, else its live account, and shows exactly what was sent, with every key hidden.

A key typed into a Tool's own header is refused when you save: the App's Account signs every call. A viewer can open a
Tool's page and run it, but not change it.

## Add Resources to the team

The App's **Resources** tab lists the agents, skills, workflows and document types it brings. **Add to team** makes your
team's own copy and opens it. A Resource your team has added reads **Added · Open**, which opens that copy. Your copy is
yours to change; the App's version stays as it was.

## Usage

The App's **Usage** tab lists this team's runs of the App's Tools, newest first. **As** says whom each ran as: a person's
email, or **Team account**.

## Approvals

Approvals are off until your team turns them on. With them off, a write runs without waiting for a person. A team turns
them on in **Settings › Policies**, three ways:

| Policy | What waits |
|---|---|
| Tool writes need approval | Every write any Tool makes |
| Apps whose writes need approval | Writes from the Apps you pick; search for an App and add it |
| A Tool's own approval switch, on its page under **Access and approval** | Writes of that one Tool |

A write that waits becomes a Human Task. A person who decides your team's reviews is not asked to approve their own
write, unless your workspace has someone else decide every request.

## A run waiting for a person

When a workflow acts for a person who has not connected their own Account of an App, the run waits instead of failing.
**Human Tasks** shows a task, **Connect your <App> account to continue**:

- The person it waits for presses **Connect my account**. Once they have connected, the run goes on by itself.
- Where the App has a team Account, someone allowed to run as it (team admins by default) can press **Run as the team
  account**, and the step goes on as the team Account.

## Turn an App off

On the App's **Settings**, **Turn off** stops the App's Tools for your team. The window lists every agent and workflow
that uses its Tools before anything stops. The App's Accounts and the Resources you added stay. The App then reads **Available** in its
header and its Settings, and **Turn on** there puts it back as it was, with no window and no sign-in.

## Who may do what

| Action | Who |
|---|---|
| Turn an App on or off, connect its team Account, add a custom App | A team admin |
| Connect your own Account, Make my default, Disconnect your own | Anyone in the team |
| Run a waiting run as the team Account | People allowed to run as the team Account; team admins by default |
| Edit an App credential | A team admin |
| Add, rotate or delete a Secret | A Security admin |
| Change the approval policies | People who manage the team's reviews |
