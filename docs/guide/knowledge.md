# Knowledge

Status: current. Rows marked planned are designed and not built.

**Let an agent answer from your own procedures and name the page and section each answer came from.**

## An agent that answers from memory gets your procedures wrong

A team's procedures, product sheets and handbooks change. An agent that answers from memory quotes last year's cash
limit with confidence, and a customer acts on it. A claims adjuster who has to check every answer against the policy
wording saves no time.

A knowledge base holds the team's own content, keeps it in step with where it lives, and lets an agent search it and
cite the page and section each answer came from. Without one, the choice is between an agent that guesses and a handbook
nobody reads.

## The plan

<!-- site: steps -->
1. **Create a base** for one body of content, such as branch policy or claims wording.
2. **Add sources.** Upload files, write pages, push items from another system or read a website, SharePoint or
   Confluence.
3. **Search it** in the Playground until the passages are the ones you expect.
4. **Give it to an agent.** The agent answers from the base and cites the page each passage came from.

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

## How a base keeps answers current

```mermaid caption="How a knowledge base keeps answers current: sources are read and indexed, and an agent answers with a citation or says it has nothing"
flowchart TD
  A[Files, pages, websites] -->|Sync| B[Read, split, indexed]
  B --> C[Knowledge base]
  C --> D[Agent searches it]
  D -->|Found| E[Cited answer]
  D -->|Nothing| F[No-answer message]
```

Sources sync on a schedule or on demand, and an unchanged item is skipped. Passages are indexed by meaning and by
keywords together, and every result says which kind of search found it. Withholding an uncited answer is on by default
in the Balanced and Precise presets. An agent searches only the bases it was given, unless its **All team knowledge
bases** option is on. A base belongs to a team, and people and agents outside the team cannot search it.

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
- Search runs on PostgreSQL only. On SQL Server a search returns no passages and says both kinds of search were skipped; it is not built there yet.
- Pages that need a browser to render (heavy JavaScript) are not read yet. Planned.

## What success looks like

You search a base and get passages with their scores and the page each came from. An agent given the base cites those
pages in its answers, and when it finds nothing to cite, the base can withhold the answer and send its no-answer message
instead. A changed page at the source is read again on the next sync, so the answer follows the handbook.

## What skipping it costs

Without a base, an agent answers from what the model remembers. The answer reads well, nobody can see where it came
from, and a wrong figure reaches a customer before anyone finds it.

## Next

<!-- site: cards -->
- **[Agents](agents.md)**: give an agent a knowledge base and publish it.
- **[Chat and channels](ops-assistant.md)**: how answers show their sources in a chat.
- **[Tools and apps](apps.md)**: read live data from your systems instead of a copy.
