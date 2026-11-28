# Salesforce

Status: current.

Your service team works cases in Salesforce, and your agents need to read and update the same cases, accounts and
contacts, and to answer from your Knowledge articles. Without the app, someone copies case details into a chat by hand,
or an agent gets a shared password that sees every record. The Salesforce app ships with Ops AI and signs in with a
Salesforce user's own permissions, so an agent never sees a record that user could not see.

## Turn it on

Before you start, a Salesforce admin installs Ops AI's connected app in your org and allows your users to use it under Manage
Connected Apps. The
commands below need the command line and a signed-in profile; see the [Quickstart](../quickstart.md).

<!-- site: steps -->
1. **Turn on the app.** A team admin opens **Data Gateway › Apps**, finds Salesforce and presses **Turn on**.
2. **Pick where the team signs in.** Choose login.salesforce.com, test.salesforce.com for a sandbox, or your company's My
   Domain address.
3. **Pick who signs in.** Choose **Everyone uses the team's login** or **Each person signs in**. Chat never asks a person
   to choose, so the answer you set here applies to every call. See [Team or personal
   sign-in](sign-in-oauth.md#team-or-personal-sign-in).
4. **Sign in.** Press **Sign in the team login** or **Sign in with my login**, and allow access on Salesforce's page. The
   app reads **Connected** once the test that follows the sign-in passes.

You can do the same from the command line:

```bash
opsai apps on plugin:opsai.salesforce --whose each   # turns the app on and prints the team account's sign-in link
opsai apps connect plugin:opsai.salesforce            # each person runs this for their own sign-in link
opsai apps test plugin:opsai.salesforce --team-account
```

`apps on` prints how many read tools were added and a link to open in a browser. After you sign in there, the test
passes. The test reads your org's API limits, so a pass shows that the sign-in reached your org.

## Check that an agent can read a case

The app reads **Connected**, and an agent that you grant its tools can answer from a case. To check it, open an agent's
Test panel and ask for the latest cases on an account. The reply lists them, and the call appears on the app's **Logs** tab
with the login it ran as.

<!-- site: sequence caption="An agent reading a case: the gateway adds the sign-in and the call is logged" -->
1. **Person → Agent**: Asks for the latest cases on an account
2. **Agent → Gateway**: Calls the case tool, holding no password
3. **Gateway → Salesforce**: Sends the call as the signed-in user, after checking the host
   - Salesforce returns only the records that user may see.
4. **Salesforce → Agent**: Returns the cases
5. **Gateway → Logs**: Records the call and the login it ran as

Without the app, nobody gets a case summary until someone pastes the case into a chat.

## Tools, articles and templates

| Kind | What | Notes |
|---|---|---|
| Read tools | Run a query, find cases by status or change time, search accounts, contacts and cases, list an account's cases, list a list view's records, read one record, and read an object's fields and picklist values | Results are paged. A query an agent writes cannot change what it reads |
| Write tools | Create, update, upsert and delete a record, and save several records in one all-or-nothing save | A deleted record goes to Salesforce's recycle bin |
| Knowledge source | Published Knowledge articles and their attachments | Syncs daily at 02:00 by default, and fetches only the articles that changed |
| Templates | A Salesforce skill, a case helper agent and a case triage workflow | **Add to team** on the app's **Agents**, **Skills** or **Workflows** tab makes your own copy |

A tool that changes a record runs straight away unless your team admin makes such changes wait for approval. [Hold a write for approval](../use-cases/approve-a-write.md)
shows how.

## Settings

| Setting | What it does | Default |
|---|---|---|
| Where do you sign in to Salesforce? | Where people sign in to Salesforce | login.salesforce.com |
| Org address | Your org's address | Read from the sign-in, never typed |
| API version | The Salesforce API version that calls use | 61.0. The person who runs Ops AI can fix it for every team |
| Article body field | The field that holds an article's text | `Body__c` |
| Records per query page | Records per page when finding cases with deleted ones | 2000 |

## What Ops AI asks Salesforce for

| Scope | Why |
|---|---|
| Know which account signed in (openid) | To show who each account is |
| Records, with the signed-in user's permissions (api) | Every tool needs it |
| Stay signed in (refresh_token) | Without it, people are signed out when the first token ends |

To use your own connected app instead of Ops AI's, see [Bring your own OAuth app](sign-in-oauth.md#bring-your-own-oauth-app).

## When Salesforce refuses the sign-in

| Message | What to do |
|---|---|
| Your Salesforce admin needs to install Ops AI's app in your org first | A Salesforce admin installs the connected app |
| Your Salesforce admin has blocked Ops AI's app | A Salesforce admin allows it |
| Your Salesforce admin needs to give you access to Ops AI's app | Add the user's profile or permission set under Manage Connected Apps |
| This Salesforce user cannot use the API | The user needs the API Enabled permission, which Professional edition does not include |
| Access was not given in Salesforce | Press **Connect** again and allow access |

## What the app does not cover

- Accounts sign in through OAuth only. A username and password or a security token is not accepted.
- A package installed inside your org, such as a lending package, runs as its own app on the org's account, and each one
  needs its own plugin.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md): from turning Salesforce on to an agent that
  works a case in chat.
- [Answer questions from your documents](../use-cases/answer-from-documents.md): add the articles source to a knowledge
  base.
- [Apps](../apps.md): accounts, sandbox accounts and turning an app off.
