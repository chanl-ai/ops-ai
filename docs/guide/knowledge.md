# Knowledge

Status: current. Rows marked planned are designed and not built.

A team's procedures, product sheets and handbooks change, and an agent that answers from memory gets them wrong. A
knowledge base holds the team's own content, keeps it in step with where it lives, and lets an agent search it and cite
the page and section each answer came from.

## Try it

Create a base, add one written page, and ask it a question. Sign in first with `opsai login` ([Install the
command line](install-cli.md)).

```bash
opsai kb create "Branch policy" --owner w.kamau@example.com
opsai kb add-text <kb-id> --title "Cash limits" --text "The daily cash withdrawal limit at a branch is 5,000."
opsai kb search <kb-id> "What is the daily cash withdrawal limit?"
```

`kb create` prints the base's id. The search answers with the passages it found, each with its score and the page it
came from. The same search runs from the base's **Playground** tab under **Knowledge bases** in the console.

To let an agent use it, open the agent, add the base under **Knowledge**, and publish the agent. Its answers then cite
the base.

## How it works

- A base is fed by one or more sources. Each source is read, split into passages, and indexed for search by meaning and
  by keywords together; every result says which kind of search found it.
- A source syncs on its schedule or on demand. A changed item is read again; an unchanged one is skipped.
- An agent searches only the bases it was given, unless its **All team knowledge bases** option is on.
- When an answer cites no passage, the base can withhold it and send its no-answer message instead. This is on by
  default in the Balanced and Precise presets.
- A base belongs to a team. People and agents outside the team cannot search it.

## Sources

| Source | What it reads | Status |
|---|---|---|
| File | Files uploaded to the base, including scans, read by OCR | built |
| Text | Pages written in the console or with `opsai kb add-text`; the same title saves a new version | built |
| Push | Items another system sends one at a time with `opsai kb push`, each with an optional link that search cites | built |
| Website, SharePoint, Confluence | Pages read through an installed plugin, picked in **Add source** | built, not yet run against a customer's own tenant |

## Settings

Each base has settings in five sections: retrieval, answer, sync, source defaults and enrichment. A preset fills them
all at once.

| Preset | What it does |
|---|---|
| Balanced (default) | Up to 8 passages, an answer with citations, an uncited answer withheld |
| Precise | Up to 5 passages with higher match floors, an answer with citations, an uncited answer withheld |
| Search only | Up to 10 passages with lower floors, returned as passages; nothing withheld |

| Sync setting | What it does |
|---|---|
| Hold changes for review | A changed item waits under **Changes** until a person accepts it |
| Keep removed items | An item removed at the source stays and is flagged instead of deleted |
| Alert on failure | A failing sync raises an alert; can be turned off |

## Limits

- Per-item visibility (who may see one document) is stored but not enforced: anyone who may search the base sees every
  item in it. Planned.
- Draft then publish for knowledge content, a query log and an unanswered-questions list are planned.
- Search runs on PostgreSQL. Search on SQL Server is planned.
- Pages that need a browser to render (heavy JavaScript) are not read yet. Planned.

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: give an agent a knowledge base and publish it.
- **[Chat and channels](ops-assistant.md)**: how answers show their sources in a chat.
- **[Tools and apps](apps.md)**: read live data from your systems instead of a copy.
