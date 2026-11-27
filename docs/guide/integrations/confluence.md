# Confluence

Status: current.

Your runbooks and procedures live in Confluence, and people edit them every week. If an agent answers from an export
made last quarter, it quotes a procedure that no longer exists. The Confluence app keeps a knowledge base current with the
spaces you pick, on Confluence Cloud or Data Center, so an agent answers from the page as it reads today and cites it.

## Turn it on and add a source

<!-- site: steps -->
1. **Turn on the app.** A team admin opens **Data Gateway › Apps**, finds Confluence and presses **Turn on**. Enter the
   site address, such as `https://yourcompany.atlassian.net/wiki`, or your Data Center's own address.
2. **Give the team's sign-in.** Use an account that can read the spaces you want. For Confluence Cloud, enter its email as the username and an API token as the password, which you create at
   id.atlassian.com under Security. For Data Center, enter a
   personal access token. Press **Run test**.
3. **Add a source.** In **Knowledge bases**, open a knowledge base, press **Add data source**, choose **From your apps**, pick Confluence and search for the
   spaces to take in. Tick **Attachments** to take in each page's attachments too.
4. **Sync.** Press **Create and sync**.

You can add the same source from the command line:

```bash
opsai kb scopes --plugin opsai.confluence --source spaces --query "Ops"
opsai kb add-source "Runbooks" --kb kb_... --plugin opsai.confluence --source spaces --value spaces=OPS
opsai kb sync kb_...
```

## Check that the pages are indexed

The **Documents** tab lists the space's pages as indexed, and the knowledge base's **Test** panel answers a question from
them with the page cited. A later sync fetches only the pages edited since the last one, so the base follows the space
without anyone exporting it.

Without the app, the agent sees an edit to a runbook only after someone exports and uploads it again.

## Pages and tools

| Kind | What |
|---|---|
| Knowledge source | The current pages of the spaces you pick, and their attachments when you ask for them |
| Read tools | List pages, read one page or attachment, list the pages changed since the last sync, and find spaces |

## Source options

| Option | What it does | Default |
|---|---|---|
| Spaces | The space keys to take in | Required |
| Attachments | Also takes in each page's attachments | Off |
| Schedule | When the source syncs | Daily at 03:00 |

## Sign-in

| Confluence | Kind | You give |
|---|---|---|
| Cloud | Username and password (basic) | The account's email and an Atlassian API token |
| Data Center | Bearer token | A personal access token |

Both are kept sealed, are never shown again, and serve only your team. See [Sign in with a key or
password](sign-in-keys.md).

## What the app does not cover

- The app is read-only. Ops AI never edits a page.
- The app has one team login. Pages are read with that login's access, so pick spaces that the whole team may read.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base from start to finish.
- [SharePoint and OneDrive](sharepoint.md): the same for document libraries.
