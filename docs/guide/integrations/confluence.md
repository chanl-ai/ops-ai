# Confluence

Status: current. Ships with Ops AI; a team admin turns it on.

When your runbooks and procedures live in Confluence, agents should answer from the current page, not last quarter's
export. The Confluence app keeps a knowledge base current with the spaces you pick, on Confluence Cloud or Data Center.

## Turn it on and add a source

<!-- site: steps -->
1. **Turn on.** A team admin opens **Data Gateway › Apps**, finds Confluence and presses **Turn on**. Enter the site
   address, such as `https://yourcompany.atlassian.net/wiki`.
2. **Give the team's sign-in.** For Confluence Cloud, an account email and an API token (basic). For Data Center, a
   personal access token (bearer). Press **Test connection**.
3. **Add a source.** In **Knowledge**, open a knowledge base, press **Add source**, pick Confluence and search for the
   spaces to take in. Tick **Attachments** to take in each page's attachments too.
4. **Sync.** Press **Create and sync**.

```bash
opsai kb scopes --plugin opsai.confluence --source spaces --query "Ops"
opsai kb add-source "Runbooks" --kb kb_... --plugin opsai.confluence --source spaces --value spaces=OPS
opsai kb sync kb_...
```

Expected: the space's pages are listed as indexed. A later sync fetches only pages edited since the last one.

## What it brings

| Kind | What |
|---|---|
| Knowledge source | The current pages of the picked spaces, and their attachments when asked |
| Read tools | List pages, read one page or attachment, list pages changed since the last sync, find spaces |

## Source options

| Option | What it does | Default |
|---|---|---|
| Spaces | The space keys to take in | Required |
| Attachments | Also take in each page's attachments | Off |
| Schedule | When the source syncs | Daily at 03:00 |

## Sign-in

| Confluence | Kind | You give |
|---|---|---|
| Cloud | Key or password (basic) | The account's email and an Atlassian API token |
| Data Center | Bearer token | A personal access token |

Both are kept sealed, are never shown again, and serve only your team. See [Sign in with a key or
password](sign-in-keys.md).

## Limits

- Read only: Ops AI never edits a page.
- One team login. Pages are read with that login's access, so pick spaces the whole team may read.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base end to end.
- [SharePoint and OneDrive](sharepoint.md): the same for document libraries.
