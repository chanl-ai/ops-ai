# Salesforce

Status: current. Ships with Ops AI; a team admin turns it on.

Your agents need to read and update cases, accounts and contacts where your service team already works, and to answer
from your Salesforce Knowledge articles. The Salesforce app gives them both, signed in with a Salesforce user's own
permissions, so an agent never sees a record that user could not.

## Turn it on

<!-- site: steps -->
1. **Turn on.** A team admin opens **Data Gateway › Apps**, finds Salesforce and presses **Turn on**.
2. **Pick where the team signs in**: login.salesforce.com, test.salesforce.com for a sandbox, or your company's My
   Domain address.
3. **Pick whose account calls use**: each person's own, the team's, or each person's with the team's for runs nobody
   started. See [Team or personal sign-in](sign-in-oauth.md#team-or-personal-sign-in).
4. **Connect.** Press **Sign in the team login** or **Sign in with my login**, and allow access on Salesforce's page.
   The App reads **Connected** once the test after sign-in passes.

The same steps from the command line:

```bash
opsai apps on plugin:opsai.salesforce --whose each   # prints the team account's sign-in link
opsai apps test plugin:opsai.salesforce --team-account
```

Expected: `apps on` prints how many read tools were added and a link to open in a browser; after you sign in there,
the test passes. The test reads your org's API limits, so a pass proves the sign-in reached your org.

## What it brings

| Kind | What | Notes |
|---|---|---|
| Read tools | Run a query, find cases by status or change time, search accounts, contacts and cases, an account's cases, a list view's records, one record, an object's fields and picklist values | Paged; a query an agent writes cannot change what it reads |
| Write tools | Create, update, upsert and delete a record, and save several records in one all-or-nothing save | A deleted record goes to Salesforce's recycle bin |
| Knowledge source | Published Knowledge articles and their attachments | Synced daily at 02:00 by default; only changed articles are fetched again |
| Templates | A Salesforce skill, a case helper agent and a case triage workflow | **Add to team** on the App's **Resources** tab makes your own copy |

Writes run at once unless your team asks first. [Hold a write for approval](../use-cases/approve-a-write.md) shows
how to make them wait.

## Settings

| Setting | What it does | Default |
|---|---|---|
| Sign-in address | Where people sign in to Salesforce | login.salesforce.com |
| Instance address | Your org's address | Read from the sign-in, never typed |
| API version | The Salesforce API version calls use | 61.0; the person who runs Ops AI can fix it for every team |
| Article body field | The field that holds an article's text | `Body__c` |
| Query batch size | Records per page of a query | 2000 |

## What Ops AI asks Salesforce for

| Scope | Why |
|---|---|
| Know which account signed in (openid) | To show who each account is |
| Records, with the signed-in user's permissions (api) | Every tool |
| Stay signed in (refresh_token) | Without it, people are signed out when the first token ends |

To use your own connected app instead of Ops AI's, see [Bring your own OAuth app](sign-in-oauth.md#bring-your-own-oauth-app).

## If sign-in fails

| Message | What to do |
|---|---|
| Your Salesforce admin needs to install Ops AI's app in your org first | A Salesforce admin installs the connected app |
| Your Salesforce admin has blocked Ops AI's app | A Salesforce admin allows it |
| Your Salesforce admin needs to give you access to Ops AI's app | Add the user's profile or permission set under Manage Connected Apps |
| This Salesforce user cannot use the API | The user needs the API Enabled permission, which Professional edition does not include |
| Access was not given in Salesforce | Press **Connect** again and allow access |

## Limits

- Accounts sign in through OAuth only; a username and password or a security token is not accepted.
- Packages installed inside an org, such as a lending package, run as their own App on the org's account. Each one is
  its own plugin.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md): from turning Salesforce on to an agent
  that works a case in chat.
- [Answer questions from your documents](../use-cases/answer-from-documents.md): add the articles source to a
  knowledge base.
- [Apps](../apps.md): accounts, sandbox accounts and turning an App off.
