# SharePoint and OneDrive

Status: current.

Your procedures and policies live as files in SharePoint document libraries, and they change. If someone copies them
into a knowledge base by hand, agents keep quoting last quarter's version and nobody notices until a customer does. The
SharePoint and OneDrive app keeps a knowledge base current with the files you pick, so agents answer from the latest
version and cite it.

## Turn it on and add a source

<!-- site: steps -->
1. **Turn on the app.** A team admin opens **Data Gateway › Apps**, finds SharePoint and OneDrive, and presses **Turn
   on**. Enter your Microsoft 365 tenant ID, or leave the default to let any work account sign in.
2. **Sign in the team login.** Use a Microsoft 365 account that can read the libraries. The first sign-in in a tenant may
   need a Microsoft 365 admin's approval.
3. **Add a source.** In **Knowledge**, open a knowledge base, press **Add source** and pick SharePoint and OneDrive. Search
   for sites, then pick whole sites or single document libraries.
4. **Sync.** Press **Create and sync**. The **Documents** tab lists each file as it is indexed.

You can add the same source from the command line:

```bash
opsai kb scopes --plugin opsai.sharepoint --source files --query "Lending"   # find the site
opsai kb add-source "Lending policies" --kb kb_... --plugin opsai.sharepoint --source files --value sites=<site id>
opsai kb sync kb_...
```

## What success looks like

The **Documents** tab lists the source's files as indexed, and the knowledge base's Playground answers a question from
them with the file cited. After that, a later sync fetches only what was added, changed or deleted, so the base follows
the library without anyone touching it.

If you skip this and copy files in by hand, each policy change waits for a person to remember it.

## What the app brings

| Kind | What |
|---|---|
| Knowledge source | The files in the sites and libraries you pick. Later syncs fetch only what was added, changed or deleted |
| Read tools | List files, read one file, list the changes since the last sync, and find sites and their libraries |

## Source options

| Option | What it does | Default |
|---|---|---|
| Sites | Takes in every document library of each site | None |
| Libraries | Takes in only these libraries, from any site or from a OneDrive | None |
| Include | Path patterns to take in, where `**` crosses folders | Everything |
| Exclude | Path patterns to leave out. Exclude wins over include | Nothing |
| Schedule | When the source syncs | Daily at 02:00 |

## What Ops AI asks Microsoft for

| Permission | Why |
|---|---|
| Read items in all site collections (Sites.Read.All) | To find sites and libraries |
| Read all files the signed-in account can read (Files.Read.All) | To read the files |
| Stay signed in (offline_access) | So that syncs keep running after the first token ends |

Ops AI only reads. It never writes to SharePoint or OneDrive.

## If sign-in fails

| Message | What to do |
|---|---|
| A Microsoft 365 admin needs to approve Ops AI's access | An admin grants consent for the tenant |
| The client secret is wrong or has expired | Enter a current secret from the Entra app registration on the app's **Auth configs** tab |
| Access was not given in Microsoft 365 | Press **Connect** again and accept |

A bank that signs in with a certificate instead of a client secret follows [Sign in with a
certificate](sign-in-certificates.md).

## Limits

- Each connection has one team login. Signing in with each person's own Microsoft account is not offered.
- Files are read with the team login's access, not with each reader's. Put only what the whole team may read in the
  source.

## Next

<!-- site: cards -->
- [Answer questions from your documents](../use-cases/answer-from-documents.md): the knowledge base from start to finish.
- [Confluence](confluence.md): the same for wiki spaces.
