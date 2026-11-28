# Sign in with a key or password

Status: current.

Many internal and vendor APIs take an API key, a username and password, or a long-lived token instead of an OAuth
sign-in. If an agent or a tool holds that secret itself, anyone who can read the agent's configuration can read the key,
and rotating it means editing every place it was pasted. Ops AI keeps the secret sealed on the app's account and adds it
to each call, so a tool, an agent or a model never holds it.

<!-- site: before-after caption="A key pasted into each tool, and a key sealed on the app's account" -->
- **Key held by the tool**: Anyone who can read the agent's configuration can read the key.
  - Rotating it means editing every place it was pasted
- **Key sealed on the account**: Ops AI adds it to each call, so no tool, agent or model holds it.
  - One key serves every tool that calls the app
  - You change it in one place

## Give the key

<!-- site: steps -->
1. **Turn the app on** in **Data Gateway › Apps**, or press **Add custom app** for an API that the catalog does not list.
2. **Enter the key** in the app's Connect window. The window asks only for the fields that the kind of sign-in needs, and
   offers a choice under **How it signs in** when the app accepts more than one kind.
3. **Press Run test.** A wrong key fails here, showing the system's own error, such as 401 Unauthorized, before any agent uses it.

The app reads **Connected** once the test passes. The key is never shown again, and a later change sends only the part you
are replacing.

If you skip the test, the first agent that calls the app is the one to find out that the key was wrong.

## The kinds

| Kind | You give | What Ops AI adds to each call |
|---|---|---|
| No sign-in | Nothing | Nothing. Public sources such as a website use this |
| API key | The key | The key, in the header or query parameter that the app names |
| Username and password (basic) | A username and a password | An `Authorization: Basic` header |
| Bearer token | A token | An `Authorization: Bearer` header |

Saving a tool is refused if you typed a key into its `Authorization`, `X-Api-Key` or `Cookie` header. Keys belong on the app's account, so one key
serves every tool that calls the app, and you change it in one place.

## Each person's own key

On an app where each person signs in, the team gives the address and how the key is sent, and each person gives their own
key. A person adds it from the chat card that asks for it, or from **My apps**.

- The key is sealed in that person's own account row and is never answered back.
- A call acting for someone who has no key yet asks them for it in place. A call that nobody started, such as a schedule,
  is refused, because there is no person to act as.
- A wrong key fails only that person's calls, and everyone else's keep working. **Disconnect** removes the key.

## Options

| Option | What it does | Default |
|---|---|---|
| Client certificate | Adds a TLS client certificate to every call, for APIs that also require mutual TLS | None. See [Sign in with a certificate](sign-in-certificates.md) |
| Sandbox account | A second account with a test key. Test runs use it, and live runs never do | None |

## What Ops AI does not do

- Ops AI does not rotate a vendor's key. Rotate it at the vendor, then enter the new one.
- An app lists which of these kinds it accepts. A custom app can switch kind with **Change sign-in** on its **Settings** tab,
  which clears its keys and tokens. A plugin's kind is fixed, so add a new account to use another.

## Next

<!-- site: cards -->
- [Build your first tool](../build-your-first-tool.md): a REST tool on an app with a bearer key.
- [Sign in with OAuth](sign-in-oauth.md)
- [Sign in with a certificate](sign-in-certificates.md)
