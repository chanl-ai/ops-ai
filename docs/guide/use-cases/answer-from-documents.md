# Answer questions from your documents

Status: current.

This guide shows you how to put a manual into a knowledge base and get answers that name the page they came from. It
takes about ten minutes and you won't need an engineer. The steps run end to end in the console, the CLI and both SDKs.

## The answer is in a manual nobody can search

Branch staff ask the same questions every day. They want to know the ATM limit, who opens a night deposit bag and
which form a payoff needs. The answers sit in manuals that nobody can search quickly, so each question goes to
whoever happens to remember, and two people can give two different answers.

A knowledge base gives everyone one place to look. You upload the manual once, and from then on an agent answers from
it. Each answer cites the document, the section and the version it quoted, so a reviewer can check it against the
page.

## The plan

<!-- site: steps -->
1. **Make a knowledge base** for one subject, such as branch procedures.
2. **Add the manual**, and write a page for any rule that isn't written down anywhere yet.
3. **Ask it** with **Test** and read the passage it returns.
4. **Give it to an agent**, so your staff get the same cited answer in chat.

## Before you start

| You need | Why |
|---|---|
| The Builder role in your team | Builders make knowledge bases |
| A document with a text layer: Markdown, Word, a text PDF | A scanned PDF with no text cannot be read |

## Try it in the console

<!-- site: steps -->
1. **Make the base.** Open **Knowledge bases**, press **New knowledge base**, give it a name such as Branch procedures, pick
   **Precise**, and press **Create knowledge base**. You land on the base's page.
2. **Add the manual.** Press **Add data source**, pick **Files** and upload a Markdown, Word or text-PDF manual (to follow the ATM
   question, use one that states the daily ATM limit). Once it is read, the **Documents** tab shows it as **Indexed**. If a file can't be read, the tab shows the reason instead, such as "no text layer".
3. **Write a page.** If a rule isn't written down in any document, press **Add data source**, pick **Typed text** and type the rule in, then press **Add page**. The page is indexed straight away.
4. **Ask it.** Press **Test** on the base's page and ask "What is the daily ATM withdrawal limit?". You get back the passage of the
   manual that answers it, along with its section, version and page.
5. **Give it to an agent.** On an agent's page, add the base under **Knowledge** and publish. When your staff ask the agent
   in chat, it answers from the base and cites the section each answer came from.

![The test sheet answering from the branch manual, with the passage, its section and its page](../../usecases/knowledge/media/uc-096-playground-1440.png)

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

Expected: the first passage that comes back quotes the page you wrote, "A night deposit bag is opened by two tellers before 9 am."

## What success looks like

You'll know it worked when three things are true. The manual shows as **Indexed** on the **Documents** tab. The test
sheet returns a passage with its section, version and page. And an agent you gave the base to answers the same
question in chat and cites the same section. When someone asks a question the base has no answer for, the agent
replies with the base's no-answer message instead of guessing.

## What skipping it costs

Without a knowledge base, an agent answers from its instructions or from the model's general knowledge. There is no
page a reviewer can open to check what it said. So if the agent gets a limit or a form wrong, the answer can reach a
customer, and you have no source to trace the mistake back to.

## Where documents can come from

| Source | Keeps itself current | Page |
|---|---|---|
| Files you upload | No. Upload a new version when the file changes | This guide |
| Pages you write | Saving the same title makes a new version | This guide |
| SharePoint and OneDrive | Yes, on a schedule, fetching only what changed | [SharePoint and OneDrive](../integrations/sharepoint.md) |
| Confluence | Yes, on a schedule | [Confluence](../integrations/confluence.md) |
| Salesforce Knowledge | Yes, daily | [Salesforce](../integrations/salesforce.md) |
| A website | Yes, from its sitemaps and links | [Website](../integrations/website.md) |

## How answers stay grounded

An agent searches only the knowledge bases you gave it, and every answer it gives carries a citation, so you can
always see where an answer came from.

<!-- site: sequence source caption="A question answered from the branch manual: the agent searches only its own bases and cites what it finds" -->
1. **Staff member → Agent**: Who opens a night deposit bag?
2. **Agent → Knowledge base**: Searches the bases the agent was given
   - A base the agent was not given is never searched.
3. **Knowledge base → Agent**: Returns the passage, its document, section and version
4. **Agent → Staff member**: Two tellers open it before 9 am, citing the manual's section
   - A question nothing answers gets the base's own no-answer message, set on its **Settings** tab.

## Limits

- A scanned PDF with no text layer is refused, and the reason is shown. Run it through OCR before you upload it.
- If an agent still cites a base you want to retire, Ops AI first names that agent, then asks you to type the base's
  name to confirm.

## Next

<!-- site: cards -->
- [Connect an app and use it in an agent](connect-an-app.md): add Salesforce articles as a source.
- [Start the day from chat](chat-and-human-tasks.md): where staff ask the agent.
