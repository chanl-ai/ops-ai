# GitHub

Status: current.

Your engineering team triages issues and answers the same questions about open work again and again. An agent can do
that, but only if it can read your repositories' issues and, when someone asks, comment on them. The GitHub app gives an
agent three actions: list issues, read one issue and add a comment. It signs in as a GitHub user, on github.com or on
your own GitHub Enterprise Server, so a comment appears under a real name instead of a shared bot account.

## Turn it on

<!-- site: steps -->
1. **Turn on the app.** A team admin opens **Data Gateway › Apps**, finds GitHub and presses **Turn on**.
2. **Pick who signs in.** Choose **Each person signs in**, so comments appear under the person's own name, or **Everyone
   uses the team's login**.
3. **Set your server's addresses** if you use GitHub Enterprise Server. Under **More options**, enter its sign-in address, such as `https://github.example.com`, and its API address, such as
   `https://github.example.com/api/v3`.
4. **Sign in.** Press **Sign in with my login** or **Sign in the team login**, and authorize on GitHub's page.

You can do most of this from the command line. It cannot set a GitHub Enterprise Server's addresses, so use the console for
that. The commands need the command line and a signed-in profile; see the [Quickstart](../quickstart.md).

```bash
opsai apps on plugin:opsai.github --whose person   # turns the app on and prints the team account's sign-in link
opsai apps connect plugin:opsai.github              # your own sign-in link
opsai apps test plugin:opsai.github --team-account   # tests the team account that the link above signed in
```

After you authorize, the test passes. It reads the signed-in GitHub user, so a pass shows that the sign-in works.

## Check an issue and a comment

The app reads **Connected**. An agent that you grant its tools can list a repository's open issues and read one in full.
When it adds a comment, the comment shows under the name of the person whose login the call used. If you chose **Each
person signs in**, the audit trail records that person's own login on the call.

Without the app, triage means someone copying issue text into a chat, and a comment posted by hand has no record of which
agent drafted it.

## What an agent can do in GitHub

| Kind | What |
|---|---|
| Read tools | List a repository's issues and pull requests, newest first and up to 50, and read one issue with its body |
| Write tool | Add a comment to an issue or pull request |
| Template | An issue helper agent. **Add to team** on the app's **Agents** tab makes your own copy |

## Settings

| Setting | What it does | Default |
|---|---|---|
| Sign-in address | Where people sign in | https://github.com |
| API address | Where calls go | https://api.github.com |
| API version | The GitHub API version that calls ask for | 2022-11-28. The person who runs Ops AI can fix it for every team |

## What Ops AI asks GitHub for

| Scope | Why |
|---|---|
| Read and comment on issues in your repositories (repo) | The three tools need it |
| Know which account signed in (read:user) | To show who each account is |

To use your own OAuth app, see [Bring your own OAuth app](sign-in-oauth.md#bring-your-own-oauth-app). Its authorization
callback URL is the Callback URL that Ops AI shows on the app's **Auth configs** tab.

## When GitHub refuses the sign-in

| Message | What to do |
|---|---|
| Access was not given in GitHub | Press **Connect** again and authorize |
| The OAuth app does not list Ops AI's return address | Add the Callback URL as the OAuth app's callback URL in GitHub |
| The OAuth app is suspended in GitHub | Its owner restores it in the OAuth app's settings |
| The client secret is wrong | Replace it on the app's **Auth configs** tab |
| The GitHub sign-in expired before it finished | Press **Connect** again |

## What the app does not cover

- The app covers issues and comments only. Pull request reviews, code and repository settings are not covered.
- A person with two GitHub accounts, such as a work one and a personal one, can connect both. When neither is picked as
  the default, the assistant asks which one to use.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md): give an agent the app's tools and use it in
  chat.
- [Sign in with OAuth](sign-in-oauth.md): team and personal sign-in, and your own OAuth app.
