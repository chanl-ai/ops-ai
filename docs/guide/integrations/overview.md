# Integrations

Status: current.

Agents and workflows are useful when they can read and act on the systems your team already uses. Each system arrives
as an App: a team admin turns it on, an account signs in once, and its tools and knowledge become available to the
team's agents, with every call going through the gateway.

## Apps that ship with Ops AI

<!-- site: cards -->
| App | What it brings | Sign-in |
|---|---|---|
| [Salesforce](salesforce.md) | Cases, accounts and contacts to read and change; Knowledge articles; a case helper agent | OAuth, team or each person |
| [GitHub](github.md) | Issues to read and comment on; an issue helper agent | OAuth, team or each person |
| [SharePoint and OneDrive](sharepoint.md) | Files in document libraries, kept current in a knowledge base | OAuth, team |
| [Amazon S3](s3.md) | Files in S3 buckets or any S3-compatible store, in a knowledge base or a watched folder | Access key, team |
| [Confluence](confluence.md) | Pages of the spaces you pick, kept current in a knowledge base | Key or token, team |
| [Website](website.md) | Pages of a website, kept current from its sitemaps and links | None |

Two more packs ship with every install and need no sign-in: the case and task types a team starts from (complaints,
account holds, document checks, write approvals and others), and starter skills for drafting, reviewing, planning and
research.

Any other REST API is an App too: **Add custom app** on **Data Gateway › Apps**, then [build a
tool](../build-your-first-tool.md) on it, or [build a plugin](build-a-plugin.md) to share it across teams.

## How an App signs in

| Kind | Use it when | Page |
|---|---|---|
| OAuth: sign in at the app, or app-to-app | The app has its own sign-in page, or a service API issues tokens to an app | [Sign in with OAuth](sign-in-oauth.md) |
| API key, username and password, or bearer token | The API takes a static secret | [Sign in with a key or password](sign-in-keys.md) |
| A certificate: signed assertion, signed service account, or mutual TLS | Your policy forbids shared secrets, or the API requires mTLS | [Sign in with a certificate](sign-in-certificates.md) |

## What holds for every App

- **Turned on per team.** Installing an App offers it to every team; each team's admin turns it on.
- **Calls go through the gateway.** Agents and workflows hold no credentials. The gateway adds the account's sign-in,
  checks the host is on the egress list, and logs the call with who it ran as.
- **Writes can wait for a person.** Writes run at once by default; a team admin can make them wait, per team, App or
  Tool. See [Hold a write for approval](../use-cases/approve-a-write.md).
- **Test accounts stay apart.** A sandbox account answers test runs; live runs never use it.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md)
- [Apps](../apps.md): states, accounts and auth configs in the console.
- [Build a plugin](build-a-plugin.md)
