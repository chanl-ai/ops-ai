# Sign in with a key or password

Status: current.

Many internal and vendor APIs take an API key, a username and password, or a long-lived token instead of an OAuth
sign-in. Ops AI keeps that secret sealed on the App's account and adds it to each call, so a Tool, an agent or a model
never holds it.

## Give the key

<!-- site: steps -->
1. **Turn the App on** in **Data Gateway › Apps**, or press **Add custom app** for an API the catalog does not list.
2. **Enter the key** in the App's Connect window. The window asks only for the fields its kind needs (below).
3. **Press Test connection.** A wrong key fails here, naming the app's own refusal (401), before any agent uses it.

Expected: the App reads **Connected**. The key is never shown again; a later change sends only the part being
replaced.

## The kinds

| Kind | You give | What Ops AI adds to each call |
|---|---|---|
| No sign-in | Nothing | Nothing. Used by public sources such as a website |
| API key | The key | The key in the header or query parameter the App names |
| Username and password (basic) | A username and a password | An `Authorization: Basic` header |
| Bearer token | A token | An `Authorization: Bearer` header |

A key typed into a Tool's own header is refused when the Tool is saved: keys belong on the App's account, so one key
serves every Tool that calls the App and is changed in one place.

## Each person's own key

On an App where each person signs in, the team gives the address and how the key is sent, and each person gives their
own key:

- From the chat card that asks for it, or from **Apps › Mine**.
- The key is sealed in that person's own account row and never answered back.
- A call acting for someone with no key yet asks them for it in place. A call nobody started (a schedule) is refused,
  since there is no person to act as.
- A wrong key fails only that person's calls; everyone else's keep working. **Disconnect** removes it.

## Options

| Option | What it does | Default |
|---|---|---|
| Client certificate | Adds a TLS client certificate to every call, for APIs that also require mutual TLS | None. See [Sign in with a certificate](sign-in-certificates.md) |
| Sandbox account | A second account with a test key; test runs use it and live runs never do | None |

## Limits

- Ops AI does not rotate a vendor's key. Rotate it at the vendor, then enter the new one.
- An App lists which of these kinds it accepts, and an account's kind cannot change once the account exists. To move
  to another kind, add a new account.

## Next

<!-- site: cards -->
- [Build your first tool](../build-your-first-tool.md): a REST Tool on an App with a Bearer key.
- [Sign in with OAuth](sign-in-oauth.md)
- [Sign in with a certificate](sign-in-certificates.md)
