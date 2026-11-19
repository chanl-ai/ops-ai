# SharePoint and OneDrive

Status: current. Ships with Ops AI; a team admin turns it on.

Procedures and policies often live as files in SharePoint document libraries. The SharePoint and OneDrive app keeps a
knowledge base current with those files, so agents answer from the latest version and cite it, without anyone copying
documents into Ops AI.

## Turn it on and add a source

<!-- site: steps -->
1. **Turn on.** A team admin opens **Data Gateway › Apps**, finds SharePoint and OneDrive, and presses **Turn on**.
   Enter your Microsoft 365 tenant ID, or leave the default to let any work account sign in.
2. **Connect the team account** and sign in with a Microsoft 365 account that can read the libraries. The first
   sign-in in a tenant may need a Microsoft 365 admin's approval.
3. **Add a source.** In **Knowledge**, open a knowledge base, press **Add source** and pick SharePoint and OneDrive.
   Search for sites, then pick whole sites or single document libraries.
4. **Sync.** Press **Create and sync**. The **Documents** tab lists each file as it is indexed.

The same source from the command line:

```bash
opsai kb scopes --plugin opsai.sharepoint --source files --query "Lending"   # find the site
opsai kb add-source "Lending policies" --kb kb_... --plugin opsai.sharepoint --source files --value sites=<site id>
opsai kb sync kb_...
```

Expected: the source's files are listed as indexed, and the base's Playground answers from them.

## What it brings

| Kind | What |
|---|---|
| Knowledge source | Files in the picked sites and libraries. Later syncs fetch only what was added, changed or deleted |
| Read tools | List files, read one file, list changes since the last sync, find sites and their libraries |

## Source options

| Option | What it does | Default |
|---|---|---|
| Sites | Take in every document library of each site | None |
| Libraries | Take in only these libraries, from any site or a OneDrive | None |
| Include | Path patterns to take in; `**` crosses folders | Everything |
| Exclude | Path patterns to leave out; exclude wins over include | Nothing |
| Schedule | When the source syncs | Daily at 02:00 |

## What Ops AI asks Microsoft for

| Permission | Why |
|---|---|
| Read items in all site collections (Sites.Read.All) | Find sites and libraries |
| Read all files the signed-in account can read (Files.Read.All) | Read the files |
| Stay signed in (offline_access) | Syncs keep running after the first token ends |

Ops AI only reads. It never writes to SharePoint or OneDrive.

## If sign-in fails

| Message | What to do |
|---|---|
| A Microsoft 365 admin needs to approve Ops AI's access | An admin grants consent for the tenant |
| The client secret is wrong or has expired | Enter a current secret from the Entra app registration on the App's **Auth configs** tab |
| Access was not given in Microsoft 365 | Press **Connect** again and accept |

A bank that signs in with a certificate instead of a client secret uses
[Sign in with a certificate](sign-in-certificates.md).

## Limits

- One team account per connection. Each person signing in with their own Microsoft account is not offered.
- A file is readable through the team account's access, not each reader's. Put only what the whole team may read in
  the source.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base end to end.
- [Confluence](confluence.md): the same for wiki spaces.
