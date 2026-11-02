# Apps

Status: current. How a team turns on the Apps its agents and workflows use, signs in to them, and controls what their
Tools may do.

An App is something outside Ops AI that your agents and workflows work with. Each App brings Tools, the actions an agent
or a workflow step can take with it, and some also bring Resources: agents, skills, workflows and document types your
team can add as its own copies. An App signs in with an Account: the team's, or a person's own.

## The Apps menu

Open **Apps** in the sidebar. Four tabs sit at the top of every page in the menu.

| Tab | What it holds |
|---|---|
| Apps | Every App your team can use. Search by name, and narrow the list with **Connected only** or **Available only**. Built in Apps, such as Files and Document types, are always on and tagged **Built in** |
| Credentials | **App credentials**, the OAuth apps your Apps sign in with, and **Secrets**, the values Tools send, such as API keys |
| My accounts | The Apps you connected with your own Account. Disconnect one here |
| Tools | Every Tool your team can use, and **Tool calls**, the log of every call they made |

**Add custom app** on the Apps tab adds an App the catalog does not list: its address and the key or sign-in it uses.

## Turn an App on

| Step | What happens |
|---|---|
| 1. Press **Connect** on the App's card | A small window opens |
| 2. Name the Account, or keep the suggested name (the App and your team) | Steps and Tools pick an Account by this name |
| 3. Keep **Team account** ticked for an Account anyone in the team can run Tools as, or untick it to connect your own | Untick it and the Account is yours alone |
| 4. Keep **App credential** on Ops AI's app, and press **Connect** | The App's own sign-in page opens; allow access there |
| 5. The window closes | The App's page opens with the Account listed as **Default** and **Connected** |

An App is **Connected** only once an Account has signed in or a test has passed; saving settings alone does not count.
A team admin turns an App on.

## Accounts: the team's and your own

The App's page lists its Accounts.

| Account | What it is |
|---|---|
| Team account | Anyone in the team can run Tools as it. The **Default** Account answers every call that names no other |
| Your account | Your own sign-in. Tools you run, and agents acting for you, use it. Press **Connect my account** to add it |

- **Connect another account** adds a second Account of the same App, under its own name, for example a second region.
  A step or a call names it to use it.
- **Make my default** makes one Account the one your own calls use when they name none.
- An Account the App stopped accepting reads **Expired** with **Reconnect**. Reconnect opens the App's sign-in page
  again; nothing is typed into Ops AI.
- On the App's **Settings**, **Everyone signs in with their own account** decides whether each person connects their own
  Account. Off, every call runs as the team Account.

## App credentials and Secrets

**Credentials › App credentials** lists the OAuth app each App signs in with: **Ops AI's app**, or **Your own app** when
your team registered its own. **Edit** replaces your own app's client secret; it is sealed when saved and never shown
again. To bring your own app, open the App's **Settings › Use your own app**, enter its client ID and secret, and
register the return address it shows. Changing the app or its permissions makes everyone connect again.

**Credentials › Secrets** lists the values Tools send, such as an API key in a header. A value is encrypted, never shown
again, and removed from whatever an App answers. A Security admin adds, rotates and deletes Secrets.

## Tools

The App's **Tools** tab lists the Tools it brings by their titles. The Apps menu's **Tools** tab lists every Tool of the
team, and **New tool** makes one of your own:

1. Name it and pick the App it calls. The App gives the address and the sign-in, so each request is a path on the App,
   such as `/accounts/{id}`.
2. Write the request on the Tool's page and press **Run** in **Mock**: it answers from the Tool's mock answers and sends
   nothing.
3. Once the Tool is published, **Real** sends the request through the App's Account and shows exactly what was sent,
   with every key hidden.

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
that uses its Tools before anything stops. The App's Accounts and the Resources you added stay; the catalog then offers
**Connect** for it again.

## Who may do what

| Action | Who |
|---|---|
| Turn an App on or off, connect its team Account, add a custom App | A team admin |
| Connect your own Account, Make my default, Disconnect your own | Anyone in the team |
| Run a waiting run as the team Account | People allowed to run as the team Account; team admins by default |
| Edit an App credential | A team admin |
| Add, rotate or delete a Secret | A Security admin |
| Change the approval policies | People who manage the team's reviews |
