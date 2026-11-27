# Sign in with OAuth

Status: current.

Most cloud apps, such as Salesforce, GitHub and Microsoft 365, let a person sign in on the app's own page and hand Ops AI
a token. Nobody types a password into Ops AI, and nobody pastes a long-lived secret into a chat where it could be read
later. This page covers the two kinds of OAuth sign-in, whose login a call uses, and how to use your own OAuth app
instead of Ops AI's. If you skip the choice of whose login to use, a scheduled run that needs a person's login is refused
when it first runs, so settle it before you build the workflow.

## Connect an account

<!-- site: steps -->
1. **Turn the app on.** A team admin opens **Data Gateway › Apps** and presses **Turn on**. Saving the app's settings
   never starts a sign-in.
2. **Sign in.** Press **Sign in the team login**, or **Sign in with my login** on the app's page or in **My apps**.
3. **Allow access** on the app's own sign-in page. The page lists what Ops AI asks for, in the app's words.
4. **Check the result.** The app reads **Connected** once the test after the sign-in passes, and the account's row shows
   who signed in.

You can do the same from the command line:

```bash
opsai apps connect plugin:opsai.github     # prints the link to open in a browser
opsai apps mine                            # your own sign-ins, one row per account
```

## The two kinds of OAuth sign-in

| Kind | Who signs in | Use it for |
|---|---|---|
| Sign in at the app (authorization code) | A person, on the app's page | Apps where calls act as a user, such as Salesforce, GitHub and SharePoint |
| App-to-app (client credentials) | Nobody. Ops AI asks the app for a token with the OAuth app's client ID and secret | Service APIs with no user, such as a payments or core-banking API |

Ops AI fetches and renews tokens itself. A token never reaches an agent, a model or a workflow step, and it is removed
from anything an app answers.

## Team or personal sign-in

When a team admin turns an app on, they choose who signs in: **Everyone uses the team's login** or **Each person signs
in**. An app lists which of these it allows. Nobody is asked to choose in a chat or in a Human Task, so the answer an
admin sets applies to every call.

| Choice | A call acting for a person | A call nobody started, such as a schedule |
|---|---|---|
| Everyone uses the team's login | The team login, with the person recorded as the one who asked | The team login |
| Each person signs in | That person's login. Without one, they are asked to sign in once | Refused, because there is no person to act as. The team's login is not used as a backup |

A refused scheduled call names the app and the two ways forward: set the app to **Everyone uses the team's login**, or
have a person start the run. When a run waits for a person, **Human Tasks** shows **Sign in to <App> to continue**, and
the run goes on by itself after they sign in.

One team's login never serves another team, and one person's token never serves anyone else.

## Bring your own OAuth app

By default an app signs in through Ops AI's own OAuth app. If the card reads **Needs an auth config**, that OAuth app is not
set up for this system, so ask whoever runs your Ops AI or bring your own. A bank that must own the
app registration uses its own.

<!-- site: steps -->
1. **Copy the callback URL.** On the app's **Auth configs** tab, press **New auth config** and copy the **Callback URL**
   it shows.
2. **Register it at the vendor.** Add that URL as the callback URL of your app, which is a Salesforce connected app, a
   GitHub OAuth app or an Entra app registration.
3. **Enter the client ID and secret** in Ops AI. The secret is sealed, and only its last four characters are shown.
4. **Connect the accounts again.** Changing the client ID or the permissions makes the accounts on it sign in again.

To prove the app with a certificate instead of a client secret, see [Sign in with a
certificate](sign-in-certificates.md).

## When a sign-in ends

| What happened | What people see | What to do |
|---|---|---|
| The token expired or was revoked | The account reads **Expired** with **Reconnect** | Press **Reconnect**. A waiting run goes on after the new sign-in |
| The client secret is wrong | Calls fail to get a token, and the account asks to be connected again | A team admin replaces the secret on the auth config, then reconnects |
| The person refused access | Access was not given | Press **Connect** again |

## Next

<!-- site: cards -->
- [Sign in with a key or password](sign-in-keys.md)
- [Sign in with a certificate](sign-in-certificates.md)
- [Apps](../apps.md): accounts, sandbox accounts and auth configs in the console.
