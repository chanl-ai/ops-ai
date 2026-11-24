# GitHub

Status: current. Ships with Ops AI; a team admin turns it on.

An agent that triages issues or answers questions about open work needs to read your repositories' issues and, when
asked, comment on them. The GitHub app gives an agent those three actions, signed in as a GitHub user, on github.com or
on your own GitHub Enterprise Server.

## Turn it on

<!-- site: steps -->
1. **Turn on.** A team admin opens **Data Gateway › Apps**, finds GitHub and presses **Turn on**.
2. **Pick whose account calls use**: each person's own (comments then show under their name), the team's, or each
   person's with the team's for runs nobody started.
3. **For GitHub Enterprise Server**, set the web and API addresses to your server's.
4. **Connect.** Press **Connect my account** or **Connect the team account** and authorize on GitHub's page.

```bash
opsai apps on plugin:opsai.github --whose person   # prints the sign-in link
opsai apps test plugin:opsai.github
```

Expected: after you authorize, the test passes; it reads the signed-in GitHub user.

## What it brings

| Kind | What |
|---|---|
| Read tools | List a repository's issues and pull requests (newest first, up to 50); read one issue with its body |
| Write tool | Add a comment to an issue or pull request |
| Template | An issue helper agent; **Add to team** on the App's **Resources** tab makes your own copy |

## Settings

| Setting | What it does | Default |
|---|---|---|
| Web address | Where people sign in | https://github.com |
| API address | Where calls go | https://api.github.com |
| API version | The GitHub API version calls ask for | 2022-11-28; the person who runs Ops AI can fix it for every team |

## What Ops AI asks GitHub for

| Scope | Why |
|---|---|
| Read and comment on issues in your repositories (repo) | The three tools |
| Know which account signed in (read:user) | To show who each account is |

To use your own OAuth app, see [Bring your own OAuth app](authentication.md#bring-your-own-oauth-app). Its
authorization callback URL is the Callback URL Ops AI shows on the App's **Auth configs** tab.

## If sign-in fails

| Message | What to do |
|---|---|
| Access was not given in GitHub | Press **Connect** again and authorize |
| The OAuth app does not list Ops AI's return address | Add the Callback URL as the OAuth app's callback URL in GitHub |
| The OAuth app is suspended in GitHub | Its owner restores it in the OAuth app's settings |
| The client secret is wrong | Replace it on the App's **Auth configs** tab |
| The GitHub sign-in expired before it finished | Press **Connect** again |

## Limits

- Issues and comments only. Pull request reviews, code and repository settings are not covered.
- A person with two GitHub accounts (work and personal) can connect both; with no default picked, the assistant asks
  which to use.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md): give an agent the app's tools and use it in
  chat.
- [Sign in with OAuth](authentication.md#sign-in-with-oauth): team and personal sign-in, and your own OAuth app.
