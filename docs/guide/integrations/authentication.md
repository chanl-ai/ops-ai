# Authentication

An App signs in to its system with OAuth, with a key or password, or with a certificate. Pick the way the system's API
asks for; each section below has the steps and what to expect.

## Sign in with OAuth

Most cloud apps (Salesforce, GitHub, Microsoft 365) let a person sign in on the app's own page and hand Ops AI a token,
so nobody types a password into Ops AI. This page covers the two OAuth sign-ins, whose account a call uses, and how to
use your own OAuth app instead of Ops AI's.

### Connect an account

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps** (a team admin). Saving the App's settings never starts a sign-in.
2. **Press Connect**: **Connect the team account**, or **Connect my account** on the App's page or on **My apps**.
3. **Allow access** on the app's own sign-in page. It lists what Ops AI asks for, in the App's words.
4. **Check the result.** The App reads **Connected** once the test after sign-in passes, and the account's row shows
   who signed in.

```bash
opsai apps connect plugin:opsai.github     # prints the link to open in a browser
opsai apps mine                            # your own sign-ins, one row per account
```

### The two OAuth kinds

| Kind | Who signs in | Use it for |
|---|---|---|
| Sign in with an account (authorization code) | A person, on the app's page | Apps where calls act as a user: Salesforce, GitHub, SharePoint |
| Client ID and secret (client credentials) | Nobody; Ops AI asks the app for a token with the OAuth app's client ID and secret | Service APIs with no user, such as a payments or core-banking API |

Ops AI fetches and renews tokens itself. A token never reaches an agent, a model or a workflow step, and is removed
from anything an app answers.

### Team or personal sign-in

When a team admin turns an App on, they pick whose account calls use. An App lists which of these it allows.

| Choice | A call acting for a person | A call nobody started (a schedule) |
|---|---|---|
| The team's account | The team account | The team account |
| Each person's own | That person's account; without one, the run waits for them to connect | Refused: there is no person to act as |
| Each person's, with the team's as backup | That person's account | The team account |

When a run waits for a person, **Human Tasks** shows it with **Connect my account**. Once they connect, the run goes
on by itself. A team admin can press **Run as the team account** instead, where the App has one.

One team's account never serves another team, and one person's token never serves anyone else.

### Bring your own OAuth app

By default an App signs in through Ops AI's own OAuth app, set up by whoever runs your Ops AI. A bank that must own the
app registration uses its own:

<!-- site: steps -->
1. On the App's **Auth configs** tab, press **New auth config** and copy the **Callback URL** it shows.
2. Register that URL as the callback URL of your app at the vendor (a Salesforce connected app, a GitHub OAuth app,
   an Entra app registration).
3. Enter the app's client ID and secret in Ops AI. The secret is sealed; only its last four characters are shown.
4. Connect the accounts again. Changing the client ID or the permissions makes the accounts on it sign in again.

To prove the app with a certificate instead of a client secret, see [Sign in with a
certificate](#sign-in-with-a-certificate).

### When a sign-in ends

| What happened | What people see | What to do |
|---|---|---|
| The token expired or was revoked | The account reads **Expired** | Press **Sign in**; a waiting run goes on after the new sign-in |
| The client secret is wrong | Calls fail to get a token and the account asks to be connected again | A team admin replaces the secret on the auth config, then reconnects |
| The person refused access | Access was not given | Press **Connect** again |

## Sign in with a key or password

Many internal and vendor APIs take an API key, a username and password, or a long-lived token instead of an OAuth
sign-in. Ops AI keeps that secret sealed on the App's account and adds it to each call, so a Tool, an agent or a model
never holds it.

### Give the key

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps**, or press **Add custom app** for an API the catalog does not list.
2. **Enter the key** in the App's Connect window. The window asks only for the fields its kind needs (below).
3. **Save.** Ops AI tests the key before it calls the App working, so a wrong key fails here, before any agent uses it.

Expected: the App reads **Connected**. The key is never shown again; a later change sends only the part being
replaced.

### The kinds

| Kind | You give | What Ops AI adds to each call |
|---|---|---|
| No sign-in | Nothing | Nothing. Used by public sources such as a website |
| API key | The key | The key in the header or query parameter the App names |
| Username and password (basic) | A username and a password | An `Authorization: Basic` header |
| Bearer token | A token | An `Authorization: Bearer` header |

A key typed into a Tool's own header is refused when the Tool is saved: keys belong on the App's account, so one key
serves every Tool that calls the App and is changed in one place.

### Each person's own key

On an App where each person signs in, the team gives the address and how the key is sent, and each person gives their
own key:

- From the chat card that asks for it, or from **My apps**.
- The key is sealed in that person's own account row and never answered back.
- A call acting for someone with no key yet asks them for it in place. A call nobody started (a schedule) is refused,
  since there is no person to act as.
- A wrong key fails only that person's calls; everyone else's keep working. **Disconnect** removes it.

### Key and password options

| Option | What it does | Default |
|---|---|---|
| Client certificate | Adds a TLS client certificate to every call, for APIs that also require mutual TLS | None. See [Sign in with a certificate](#sign-in-with-a-certificate) |
| Test account | A second account with a test key; test runs use it and live runs never do | None |

### Key and password limits

- Ops AI does not rotate a vendor's key. Rotate it at the vendor, then enter the new one.
- An App lists which of these kinds it accepts, and an account's kind cannot change once the account exists. To move
  to another kind, add a new account.

## Sign in with a certificate

Banks often forbid shared client secrets: an app registration must prove itself with a certificate whose private key
the bank controls, and some APIs also require mutual TLS. Ops AI supports three certificate sign-ins, and keeps the key
sealed so no person, Tool or model can read it back.

### Set it up

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps**, or open its **Auth configs** tab.
2. **Pick the certificate option** in the Connect window (below) and paste the certificate and its private key, in PEM.
3. **Save.** A key that does not belong to its certificate is refused, naming both.
4. **Check the account.** Its row shows the certificate's SHA-256 thumbprint, subject and expiry, and warns when it
   expires within 30 days. The key is never shown.

### Certificate options

| Option | What it does | You give | Typical use |
|---|---|---|---|
| OAuth app proves itself with a certificate | Every token request, refresh and sign-in carries a client assertion signed by your key, in place of a client secret | Client ID, signing certificate, signing key | Microsoft Entra app registrations at banks |
| Signed service account (JWT bearer) | Ops AI asks for a token with a JWT signed by your key, and signs a new one when it expires. No person signs in | Client ID (the issuer), signing key; optionally certificate, subject, audience, and whether scopes go in the form or the claim | DocuSign (the integration key, a user ID as subject) and Google service accounts |
| Client certificate (mutual TLS) | Presents your certificate on the TLS handshake of every call, with any of the kinds above or a key | Client certificate, client key, and optionally a trusted CA | APIs on a private network that require mTLS |

The signing pair and the TLS pair are kept apart, so a signing key is never offered on a TLS handshake.

### What fails, and how it reads

| Case | What happens |
|---|---|
| The signing certificate has expired | Refused before any token request: "the signing certificate expired on <date>". The account asks to be connected again |
| The app refuses the assertion (another key, a replay) | The sign-in fails naming the app's host and error. It is never retried with a secret |
| The TLS handshake is refused | The call fails as a TLS failure, naming the host |

### Certificate limits

- Keys are RSA (RS256) or P-256 (ES256). Any other key is refused.
- Ops AI does not renew certificates. Renew at your CA, then paste the new pair; the 30-day warning is the reminder.

## Next

<!-- site: cards -->
- [Apps](../apps.md): accounts, test accounts and auth configs in the console.
- [Build your first tool](../build-your-first-tool.md): a REST Tool on an App with a Bearer key.
- [SharePoint and OneDrive](sharepoint.md): an Entra app that can use a certificate.
