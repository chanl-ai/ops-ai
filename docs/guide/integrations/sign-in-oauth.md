# Sign in with OAuth

Status: current.

Most cloud apps (Salesforce, GitHub, Microsoft 365) let a person sign in on the app's own page and hand Ops AI a token,
so nobody types a password into Ops AI. This page covers the two OAuth sign-ins, whose account a call uses, and how to
use your own OAuth app instead of Ops AI's.

## Connect an account

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps** (a team admin). Saving the App's settings never starts a sign-in.
2. **Sign in**: **Sign in the team login**, or **Sign in with my login** on the App's page or in **My apps**.
3. **Allow access** on the app's own sign-in page. It lists what Ops AI asks for, in the App's words.
4. **Check the result.** The App reads **Connected** once the test after sign-in passes, and the account's row shows
   who signed in.

```bash
opsai apps connect plugin:opsai.github     # prints the link to open in a browser
opsai apps mine                            # your own sign-ins, one row per account
```

## The two OAuth kinds

| Kind | Who signs in | Use it for |
|---|---|---|
| Sign in at the app (authorization code) | A person, on the app's page | Apps where calls act as a user: Salesforce, GitHub, SharePoint |
| App-to-app (client credentials) | Nobody; Ops AI asks the app for a token with the OAuth app's client ID and secret | Service APIs with no user, such as a payments or core-banking API |

Ops AI fetches and renews tokens itself. A token never reaches an agent, a model or a workflow step, and is removed
from anything an app answers.

## Team or personal sign-in

When a team admin turns an App on, they pick who signs in: **Everyone uses the team's login** or **Each person signs
in**. An App lists which of these it allows.

| Choice | A call acting for a person | A call nobody started (a schedule) |
|---|---|---|
| Everyone uses the team's login | The team login, with the person recorded as the one who asked | The team login |
| Each person signs in (app allows no team login) | That person's login; without one, they are asked to sign in once | Refused: there is no person to act as |
| Each person signs in (app allows a team login) | That person's login | The team login |

When a run waits for a person, **Human Tasks** shows **Sign in to <App> to continue**. Once they sign in, the run goes
on by itself.

One team's account never serves another team, and one person's token never serves anyone else.

## Bring your own OAuth app

By default an App signs in through Ops AI's own OAuth app, set up by whoever runs your Ops AI. A bank that must own the
app registration uses its own:

<!-- site: steps -->
1. On the App's **Auth configs** tab, press **New auth config** and copy the **Callback URL** it shows.
2. Register that URL as the callback URL of your app at the vendor (a Salesforce connected app, a GitHub OAuth app,
   an Entra app registration).
3. Enter the app's client ID and secret in Ops AI. The secret is sealed; only its last four characters are shown.
4. Connect the accounts again. Changing the client ID or the permissions makes the accounts on it sign in again.

To prove the app with a certificate instead of a client secret, see [Sign in with a
certificate](sign-in-certificates.md).

## When a sign-in ends

| What happened | What people see | What to do |
|---|---|---|
| The token expired or was revoked | The account reads **Expired** with **Reconnect** | Press **Reconnect**; a waiting run goes on after the new sign-in |
| The client secret is wrong | Calls fail to get a token and the account asks to be connected again | A team admin replaces the secret on the auth config, then reconnects |
| The person refused access | Access was not given | Press **Connect** again |

## Next

<!-- site: cards -->
- [Sign in with a key or password](sign-in-keys.md)
- [Sign in with a certificate](sign-in-certificates.md)
- [Apps](../apps.md): accounts, sandbox accounts and auth configs in the console.
