# Answer questions from your documents

Status: current. The steps below run end to end in the console, the CLI and both SDKs.

**Put a manual into a knowledge base and get answers that name the page they came from, in about ten minutes and
without an engineer.**

## The answer is in a manual nobody can search

Branch staff ask the same questions every day: what is the ATM limit, who opens a night deposit bag, which form a
payoff needs. The answers are in manuals nobody can search quickly, so each question goes to whoever remembers, and
two people can give two different answers.

A knowledge base fixes that. You upload the manual once, and an agent answers from it and cites the document, the
section and the version it quoted, so a reviewer can check the answer against the page.

## The plan

<!-- site: steps -->
1. **Make a knowledge base** for one subject, such as branch procedures.
2. **Add the manual**, and write a page for any rule that lives in nobody's document.
3. **Ask it** in the Playground and read the passage it returns.
4. **Give it to an agent**, so staff get the same cited answer in chat.

## Before you start

| You need | Why |
|---|---|
| The Builder role in your team | Builders make knowledge bases |
| A document with a text layer: Markdown, Word, a text PDF | A scanned PDF with no text cannot be read |

## Try it in the console

<!-- site: steps -->
1. **Make the base.** Open **Knowledge**, press **New knowledge base**, give it a name such as Branch procedures, pick
   **Precise**, and press **Create**. You land on the base's page.
2. **Add the manual.** Press **Add source**, pick **Files**, upload the manual and press **Create and sync**. The
   **Documents** tab shows it as **Indexed**. A file with no text layer shows its reason, such as "no text layer".
3. **Write a page.** For a rule that lives in nobody's document, press **Add page** on the **Documents** tab and type
   it. It is indexed at once.
4. **Ask it.** On the **Playground** tab, ask "What is the daily ATM withdrawal limit?". The answer is a passage of the
   manual with its section, version and page.
5. **Give it to an agent.** On an agent's page, add the base under **Knowledge** and publish. In chat, the agent answers
   from it and cites the section each answer came from.

![The Playground answering from the branch manual, with the passage, its section and its page](../../usecases/knowledge/media/uc-096-playground-1440.png)

## From the CLI or SDK

```bash tab="CLI"
KB=$(opsai kb create "Branch procedures" --owner branch.ops@example.com --json | jq -r .id)
opsai kb add-file "$KB" ./branch-operations-manual.md
opsai kb add-text "$KB" --title "Night deposit" --text "A night deposit bag is opened by two tellers before 9 am."
opsai kb search "$KB" "What is the daily ATM withdrawal limit?"
opsai chat say --kb "$KB" -m "Who opens a night deposit bag?"
```

```python tab="Python"
from ops_ai import OpsAI

ops = OpsAI(profile="builder")
kb = ops.knowledge.add_base("Branch procedures", owner="branch.ops@example.com")
ops.knowledge.add_page(kb["id"], "Night deposit", "A night deposit bag is opened by two tellers before 9 am.")
found = ops.knowledge.search({"kbIds": [kb["id"]], "question": "Who opens a night deposit bag?"})
print(found["passages"][0]["text"])
```

```ts tab="TypeScript"
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ profile: 'builder' });
const kb = await ops.knowledge.addBase('Branch procedures', { owner: 'branch.ops@example.com' });
await ops.knowledge.addPage(kb.id, 'Night deposit', 'A night deposit bag is opened by two tellers before 9 am.');
const found = await ops.knowledge.search({ kbIds: [kb.id], question: 'Who opens a night deposit bag?' });
console.log(found.passages[0].text);
```

Expected: the first passage quotes the page: "A night deposit bag is opened by two tellers before 9 am."

## What success looks like

The manual's **Documents** tab shows **Indexed**, the Playground returns a passage with its section, version and page,
and an agent given the base answers the same question in chat and cites the same section. A question the base cannot
answer gets its no-answer message, not a guess.

## What skipping it costs

Without a knowledge base, an agent answers from its instructions or from the model's general knowledge, with no page a
reviewer can open to check it. The first wrong answer about a limit or a form reaches a customer with nothing to trace
it to.

## Where documents can come from

| Source | Keeps itself current | Page |
|---|---|---|
| Files you upload | No; upload a new version | This guide |
| Pages you write | Saving the same title makes a new version | This guide |
| SharePoint and OneDrive | Yes, on a schedule; only changes are fetched | [SharePoint and OneDrive](../integrations/sharepoint.md) |
| Confluence | Yes, on a schedule | [Confluence](../integrations/confluence.md) |
| Salesforce Knowledge | Yes, daily | [Salesforce](../integrations/salesforce.md) |
| A website | Yes, from its sitemaps and links | [Website](../integrations/website.md) |

## How answers stay grounded

An agent searches only the bases it was given, and every answer carries its citation.

<!-- site: sequence source caption="A question answered from the branch manual: the agent searches only its own bases and cites what it finds" -->
1. **Staff member → Agent**: Who opens a night deposit bag?
2. **Agent → Knowledge base**: Searches the bases the agent was given
   - A base the agent was not given is never searched.
3. **Knowledge base → Agent**: Returns the passage, its document, section and version
4. **Agent → Staff member**: Two tellers open it before 9 am, citing the manual's section
   - A question nothing answers gets the base's own no-answer message, set on its **Settings** tab.

## Limits

- A scanned PDF with no text layer is refused with its reason; run it through OCR first.
- Retiring a base an agent still cites asks you to type its name, and names the agent first.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](connect-an-app.md): add Salesforce articles as a source.
- [Start the day from chat](chat-and-human-tasks.md): where staff ask the agent.
