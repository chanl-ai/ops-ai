# Knowledge

Status: current. Rows marked planned are designed and not built.

## Why an agent needs your own procedures

Your team's procedures, product sheets and handbooks change over time, but a model only knows what it learned when it
was trained. An agent that answers from that memory can quote last year's cash limit with full confidence, and a
customer may then act on the wrong figure. If a claims adjuster has to check every answer against the policy wording,
the agent saves them no time.

A knowledge base lets an agent answer from your own procedures instead. It holds your team's content and keeps it in
step with the place where that content lives, so the agent can search it and name the page and section each answer came
from. Without one, you are left choosing between an agent that guesses and a handbook nobody reads.

## Setting up a knowledge base

<!-- site: steps -->
1. **Create a base** for one body of content, such as your branch policy or your claims wording.
2. **Add sources.** You can upload files, write pages, push items from another system, or read a website, SharePoint
   or Confluence.
3. **Search it** in the Playground with a few real questions, and keep going until the passages it returns are the
   ones you expect.
4. **Give it to an agent.** The agent then answers from the base and cites the page each passage came from.

## Try it from the command line

You can create a base, add one written page and ask it a question with three commands. Sign in first with
`opsai login` ([Install the command line](install-cli.md)).

```bash
opsai kb create "Branch policy" --owner w.kamau@example.com
opsai kb add-text <kb-id> --title "Cash limits" --text "The daily cash withdrawal limit at a branch is 5,000."
opsai kb search <kb-id> "What is the daily cash withdrawal limit?"
```

`kb create` prints the id of the new base, which the other two commands take. The search returns the passages it
found, each with its score and the page it came from. You can run the same search in the console from the base's
**Playground** tab under **Knowledge bases**.

To let an agent use the base, open the agent, add the base under **Knowledge** and publish the agent. From then on, its
answers cite the base.

## How a base keeps answers current

```mermaid caption="How a knowledge base keeps answers current: sources are read and indexed, and an agent answers with a citation or says it has nothing"
flowchart TD
  A[Files, pages, websites] -->|Sync| B[Read, split, indexed]
  B --> C[Knowledge base]
  C --> D[Agent searches it]
  D -->|Found| E[Cited answer]
  D -->|Nothing| F[No-answer message]
```

Each source syncs on a schedule or whenever you ask it to, and an item that has not changed since the last sync is
skipped. Passages are indexed by meaning and by keywords together, and every search result shows which kind of search
found it.

In the Balanced and Precise presets, an answer without a citation is withheld by default. An agent searches only the
bases it has been given, unless its **All team knowledge bases** option is turned on. Each base belongs to a team, so
people and agents outside that team cannot search it.

## Sources

| Source | What it reads | Status |
|---|---|---|
| File | Files uploaded to the base, including scans, read by OCR | built |
| Text | Pages written in the console or with `opsai kb add-text`; the same title saves a new version | built |
| Push | Items another system sends one at a time with `opsai kb push`, each with an optional link that search cites | built |
| Website, SharePoint, Confluence | Pages read through an installed plugin, picked in **Add source** | built, not yet run against a customer's own tenant |

## Settings

Each base's settings are grouped into five sections: retrieval, answer, sync, source defaults and enrichment. When you
pick a preset, it fills in all five sections at once.

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

## What is not built yet

- Per-item visibility, which sets who may see a single document, is stored but not enforced. Until it is, anyone who
  may search a base sees every item in it. Enforcement is planned.
- Drafting and then publishing knowledge content, a query log and a list of unanswered questions are all planned.
- Search runs on PostgreSQL only. It is not built for SQL Server yet, so a search there returns no passages and reports
  that both kinds of search were skipped.
- Pages that need a browser to render, such as pages built with heavy JavaScript, are not read yet. Support is planned.

## When it is working

When you search a base, you get passages with their scores and the page each one came from. An agent given the base
cites those pages in its answers. When it finds nothing to cite, the base can withhold the answer and send its
no-answer message instead. Because a page that changes at the source is read again on the next sync, the agent's
answers keep up with the handbook.

## Without a knowledge base

Without a base, an agent answers from what the model remembers. The answer may read well, but nobody can see where it
came from, so a wrong figure can reach a customer before anyone notices.

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: give an agent a knowledge base and publish it.
- **[Chat and channels](ops-assistant.md)**: how answers show their sources in a chat.
- **[Tools and apps](apps.md)**: read live data from your systems instead of a copy.
