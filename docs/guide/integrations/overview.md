# Integrations

Status: current.

Your agents and workflows are only as useful as the systems they can reach. A card dispute needs the card ledger, a
service case needs Salesforce, and a policy question needs the documents in SharePoint or Confluence. If every agent
holds its own copy of a password for each system, nobody can tell who used which credential, and the first leaked
key reaches everything. Ops AI brings each system in as an app. A team admin turns the app on, someone signs in once,
and its tools and knowledge become available to the team's agents. Every call goes through the gateway, which holds the
sign-in so agents never do.

## The apps that ship with Ops AI

<!-- site: cards -->
| App | What it brings | Sign-in |
|---|---|---|
| [Salesforce](salesforce.md) | Cases, accounts and contacts to read and change, Knowledge articles, and a case helper agent | OAuth, team or each person |
| [GitHub](github.md) | Issues to read and comment on, and an issue helper agent | OAuth, team or each person |
| [SharePoint and OneDrive](sharepoint.md) | Files in document libraries, kept current in a knowledge base | OAuth, team |
| [Confluence](confluence.md) | Pages of the spaces you pick, kept current in a knowledge base | Key or token, team |
| [Website](website.md) | Pages of a website, kept current from its sitemaps and links | None |

Two more packs ship with every install and need no sign-in. One holds the case and task types a team starts from, such as
complaints, account holds, document checks and write approvals. The other holds starter skills for drafting, reviewing,
planning and research.

To try it now, open **Data Gateway › Apps** and turn on Website, which needs no sign-in.

Any other REST API can be an app too. Press **Add custom app** on **Data Gateway › Apps** and [build a
tool](../build-your-first-tool.md) on it, or [build a plugin](build-a-plugin.md) to share it across teams.

## How an app signs in

Each app accepts one or more kinds of sign-in. Pick the page that matches what the system's API asks for.

| Kind | Use it when | Page |
|---|---|---|
| OAuth, either signing in at the app or app-to-app | The app has its own sign-in page, or a service API issues tokens to an app | [Sign in with OAuth](sign-in-oauth.md) |
| API key, username and password, or bearer token | The API takes a static secret | [Sign in with a key or password](sign-in-keys.md) |
| A certificate: signed assertion, signed service account, or mutual TLS | Your policy forbids shared secrets, or the API requires mutual TLS | [Sign in with a certificate](sign-in-certificates.md) |

## What holds for every app

- A team admin turns an app on for each team. Installing an app offers it to every team, but it works for a team only
  after that team's admin turns it on.
- Agents and workflows hold no credentials. The gateway adds the account's sign-in to each call, checks that the host is
  allowed, and logs the call with who it ran as.
- By default, a tool that changes data runs as soon as an agent calls it. A team admin can make those changes wait for a
  person to approve them, for the whole team, for one app or for one tool. See [Hold a write for approval](../use-cases/approve-a-write.md).
- A sandbox account answers test runs, and live runs never use it, so a test cannot change real records.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](../use-cases/connect-an-app.md)
- [Apps](../apps.md): states, accounts and auth configs in the console.
- [Build a plugin](build-a-plugin.md)
