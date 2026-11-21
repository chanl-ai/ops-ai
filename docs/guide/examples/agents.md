# Agent examples

Status: current.

An agent answers people in a chat, inside the instructions, knowledge and tools you give it. These examples take one
agent from a first draft to a published agent that answers from a knowledge base, may call a tool, and is scored with
test cases.

Connect first: see [Before you start](README.md#before-you-start). Each example carries on from the one before it.

## What each surface can do

| Task | Python | TypeScript | Command line |
|---|---|---|---|
| Create, update and publish an agent | built | built, create only | built |
| Chat and keep the conversation | built | built | built |
| Answer from a knowledge base | built | built | built |
| Grant a tool | built | built | built |
| Test a draft | built | built | built |
| Run and stream every event | built | upcoming | built |
| Run in the background | partial | upcoming | upcoming |
| Score with cases | built | upcoming | upcoming |
| Write the agent as a brief, check what blocks a publish, add what the brief mentions | upcoming | upcoming | upcoming |

## Create and publish an agent

**The problem.** You want an agent your team can chat with, kept as a file or a few lines of code so a change is
reviewed like any other change.

**When to use it.** Every agent starts here. An agent has a draft and a published version. People chat with the
published version, so a change reaches them only after you publish it.

Python. `apply` creates the agent, or updates the draft of the agent that already has this name.

```python
from ops_ai import OpsAI

ops = OpsAI()

agent = ops.agents.apply({
    "name": "Returns helper",
    "role": "Answer questions about the returns policy",
    "instructions": "Answer in two sentences. Items can be returned within 30 days with a receipt.",
})
request = ops.agents.publish(agent["id"], note="First version")
print(agent["id"], request["status"])
```

TypeScript. `apply` creates a new agent each time, so call it once and keep the id.

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const agent = await ops.agents.apply({
  name: 'Returns helper (TypeScript)',
  role: 'Answer questions about the returns policy',
  instructions: 'Answer in two sentences. Items can be returned within 30 days with a receipt.',
});
const request = await ops.agents.publish(agent.id, 'First version');
console.log(agent.id, request.status);
```

Command line. The agent is a YAML or JSON file.

```yaml title="returns-helper.yaml"
name: Returns helper
role: Answer questions about the returns policy
instructions: Answer in two sentences. Items can be returned within 30 days with a receipt.
```

```bash
opsai agents validate returns-helper.yaml
AGENT=$(opsai agents --json apply returns-helper.yaml | jq -r .id)
opsai agents publish "$AGENT" --note "First version"
```

| Field | What it does |
|---|---|
| `name` | The agent's name. Python and the command line use it to find the agent to update |
| `role` | One line on what the agent is for. Required |
| `instructions` | What the agent is told before every conversation |
| `model` | A model your deployment offers. Left out, the agent uses the default |
| `collections` | The knowledge bases it may search, by id |
| `toolIds` | The tools it may call, by id |
| `guardrails` | Limits such as the most tool calls in one reply |
| `memory` | Whether it remembers facts between conversations |

`validate` checks that a file has a name and a role before anything is sent. The publish request comes back with its
status. It is `approved` when no reviewer is needed.

## Chat and keep the conversation

**The problem.** You want to ask the published agent a question from a script, then ask a follow-up in the same
conversation.

**When to use it.** Use it for a quick check after a publish, and for any program that talks to an agent on a
person's behalf.

```python
first = ops.agents.chat(agent["id"], "Can I return shoes after two weeks?")
print(first["reply"])

again = ops.agents.chat(agent["id"], "And without a receipt?", thread_id=first["threadId"])
print(again["reply"])
```

TypeScript. `ops.chat` opens a conversation and returns each reply's events; the last one carries the whole message.

```ts
const thread = await ops.chat.start(agent.id);

const first = await ops.chat.say(thread.id, 'Can I return shoes after two weeks?');
console.log(first.at(-1).message.content);

const again = await ops.chat.say(thread.id, 'And without a receipt?');
console.log(again.at(-1).message.content);
```

```bash
opsai agents chat "$AGENT" --message "Can I return shoes after two weeks?"

THREAD=$(opsai chat say --agent "$AGENT" -m "Can I return shoes after two weeks?" --json | jq -r .thread)
opsai chat say --thread "$THREAD" -m "And without a receipt?"
```

What `ops.agents.chat` returns in Python:

| Field | What it holds |
|---|---|
| `reply` | The agent's full reply as text |
| `threadId` | The conversation. Pass it back to continue |
| `toolCalls` | The tools the agent called in this reply |
| `citations` | The knowledge passages the reply used |
| `events` | Every event of the reply, in order |

In TypeScript, read the reply from `ops.chat.say` as shown. `ops.agents.chat` also exists there, and its `reply` field
holds only the last piece of the streamed text.

## Answer from a knowledge base

**The problem.** The agent should answer from your policy pages and show which page it used. Policy text does not
belong in the instructions, where nobody can see what the answer came from.

**When to use it.** Use it when answers must come from text your team owns and updates.

```python
base = ops.knowledge.add_base("Store policies", owner="returns.lead@example.com")
ops.knowledge.add_page(base["id"], "Returns", "Items can be returned within 30 days with a receipt. Sale items are final.")

ops.agents.apply({
    "name": "Returns helper",
    "role": "Answer questions about the returns policy",
    "instructions": "Answer in two sentences from the Store policies knowledge base. Say so when the page does not answer.",
    "collections": [base["id"]],
})
ops.agents.publish(agent["id"], note="Answers from Store policies")

answer = ops.agents.chat(agent["id"], "How long do I have to return an item?")
for citation in answer["citations"]:
    print(citation["title"], citation["snippet"])
```

TypeScript. `apply` does not take knowledge bases, so the update uses the operation by its API name.

```ts
const base = await ops.knowledge.addBase('Store policies (TypeScript)', { owner: 'returns.lead@example.com' });
await ops.knowledge.addPage(base.id, 'Returns', 'Items can be returned within 30 days with a receipt. Sale items are final.');

await ops.raw.agents.agents_update_agent({ path: { agent_id: agent.id }, body: { collections: [base.id] } });
await ops.agents.publish(agent.id, 'Answers from Store policies');

const answer = await ops.chat.say(thread.id, 'How long do I have to return an item?');
for (const citation of answer.at(-1).message.citations) console.log(citation.title, citation.snippet);
```

```bash
KB=$(opsai kb create "Store policies (CLI)" --owner returns.lead@example.com --json | jq -r .id)
SOURCE=$(opsai kb add-source Policies --kb "$KB" --json | jq -r .id)
opsai kb push "$SOURCE" --name returns --title Returns \
  --text "Items can be returned within 30 days with a receipt. Sale items are final."

cat > returns-helper.yaml <<EOF
name: Returns helper
role: Answer questions about the returns policy
instructions: Answer in two sentences from the Store policies knowledge base. Say so when the page does not answer.
collections: [$KB]
EOF
opsai agents apply returns-helper.yaml
opsai agents publish "$AGENT" --note "Answers from Store policies"
opsai agents chat "$AGENT" --message "How long do I have to return an item?"
```

A knowledge base needs an owner: the person who answers for what it serves. Saving a page under a title that already
exists saves a new version of that page.

## Grant a tool

**The problem.** The agent should be able to act, for example open a case, and only with tools your team has
published.

**When to use it.** Use it when a reply needs live data or needs to change something. A grant is a change to the
draft, so publish again for it to take effect.

```python
for option in ops.agents.tool_options("case"):
    print(option["id"], option["label"])

ops.agents.grant_tools(agent["id"], ["open_case"])
ops.agents.publish(agent["id"], note="May open a case")
```

```ts
for (const option of await ops.agents.toolOptions('case')) console.log(option.id, option.label);

await ops.agents.grantTools(agent.id, ['open_case']);
await ops.agents.publish(agent.id, 'May open a case');
```

```bash
opsai agents tool-options --search case
opsai agents grant-tools "$AGENT" open_case
opsai agents publish "$AGENT" --note "May open a case"
```

`tool_options` lists what the agent may be granted: tools, other agents (`agent:<id>`) and published workflows
(`workflow:<id>`). `grant_tools` adds to the tools the agent already holds. When your team's policy makes writes wait
for approval, a tool that changes something pauses the reply until a person approves the call.

## Test a draft

**The problem.** You changed the draft and want to see how it answers before the change reaches anyone.

**When to use it.** Use it between `apply` and `publish`.

```python
tried = ops.agents.test(agent["id"], "Can I return a gift?")
print(tried["model"], tried["searched"], tried["tools"], tried["skills"])
```

```ts
const tried = await ops.agents.test(agent.id, 'Can I return a gift?');
console.log(tried.model, tried.searched, tried.tools, tried.skills);
```

```bash
opsai agents test "$AGENT" --message "Can I return a gift?"
```

The answer holds the reply and what produced it: the model, whether knowledge was searched, the tool calls, the
skills and guardrails that applied, and the time it took.

## Run in the background

**The problem.** A long reply should not hold your program up. You want to start the agent, go on, and read the
conversation later.

**When to use it.** Use `wait` for a script that needs the reply, `stream` when you want every event, and `background`
when your program has other work to do while the agent replies.

```python
started = ops.agents.run(agent["id"], "Summarise the returns policy.", mode="background")
print(started["threadId"], started["runId"])

for recent in ops.agents.trace(agent["id"], limit=5):
    print(recent["threadId"], recent["status"])
```

```bash
opsai agents run "$AGENT" --message "Summarise the returns policy." --mode stream
opsai agents trace "$AGENT"
```

| Mode | What comes back |
|---|---|
| `wait` | The collected reply, as `chat` returns it. The default |
| `stream` | The same reply, with every event kept in `chunks` |
| `background` | The thread and run ids at once. The reply is on the thread when it finishes |

A background run is carried by the program that started it. Keep that program running until the reply is on the
thread: a script that exits straight after the call loses the run, and so does the command line, which exits as soon
as it has printed the ids. Runs that carry on without the caller are upcoming.

## Score with cases

**The problem.** You want to know that a change did not break the answers you care about.

**When to use it.** Use it before publishing a change to instructions, knowledge or tools. Each case is an input and
the checks its reply must pass.

```python
scored = ops.agents.eval(agent["id"], [
    {
        "name": "return window",
        "input": "How long do I have to return an item?",
        "checks": [{"type": "reply_contains", "text": "30 days"}],
    },
])
print(scored["summary"])
for result in scored["results"]:
    print(result["caseName"], result["draft"]["status"])
```

| Check | Passes when |
|---|---|
| `reply_contains` | The reply holds `text` |
| `calls_tool` | The agent called `tool` |
| `refuses` | The agent refused, and the refusal holds `text` |

The summary counts the cases that passed, the total, and regressions: cases the published version passes and the
draft fails.

## Upcoming: write the agent as a brief

> [!NOTE]
> **Upcoming.** This section is in review and is not in the current release. Its examples were run against the code
> under review.

**The problem.** One long block of instructions mixes what the agent is for, how it should answer and what it must
never do. A reviewer cannot tell which line is a hard rule.

**When to use it.** Use a brief for a new agent. The platform writes the agent's instructions from the brief, and
sends the never rules to the model again before every reply. An agent saved without a brief keeps working from its
instructions as before.

```yaml title="accounts-desk.yaml"
name: Accounts desk
role: Answers staff questions about a customer's accounts
brief:
  purpose: Answers branch staff questions about a customer's accounts.
  goal: Staff have the answer, or know who to ask.
  howToAnswer: Look the customer up with @tool:search_customers before you say anything about them. Keep answers short.
  never:
    - Never read out a full account number.
  success:
    - Staff know which customer the answer is about.
patterns:
  thinking: low
```

```python
from ops_ai import OpsAI

ops = OpsAI()

agent = ops.agents.apply("accounts-desk.yaml")
print(agent["promptMode"])

check = ops.agents.publish_check(agent["id"])
for problem in check["problems"]:
    print(problem["kind"], problem["id"], problem["position"]["field"])

ops.agents.add_reference(agent["id"], "tool", "search_customers")
print(ops.agents.publish_check(agent["id"])["canRequest"])

request = ops.agents.publish(agent["id"], note="First version")
print(request["status"])
```

TypeScript takes the same fields as an object.

```ts
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();

const agent = await ops.agents.apply(parse(readFileSync('accounts-desk.yaml', 'utf8')));
console.log(agent.promptMode);

const check = await ops.agents.publishCheck(agent.id);
for (const problem of check.problems) console.log(problem.kind, problem.id, problem.position.field);

await ops.agents.addReference(agent.id, 'tool', 'search_customers');
console.log((await ops.agents.publishCheck(agent.id)).canRequest);

const request = await ops.agents.publish(agent.id, 'First version');
console.log(request.status);
```

```bash
AGENT=$(opsai agents apply accounts-desk.yaml --json | jq -r .id)
opsai agents publish-check "$AGENT"
opsai agents references "$AGENT" --search customer --kind tool
opsai agents add-reference "$AGENT" tool search_customers
opsai agents publish-check "$AGENT"
opsai agents publish "$AGENT" --note "First version"
```

The publish check also carries the agent's evals. A blocking step that failed on the newest run of that exact version
is `eval_failed`, and the publish is refused; an approval of a request whose version failed after it opened is 409
`eval_blocked`. With the team's "Require passing evals to publish" setting (`evalsRequired`) on, no saved cases is
`eval_no_cases` and no run on the version is `eval_not_run`; a setting that cannot be read is `eval_setting_unread`.

| Field | What it does |
|---|---|
| `brief.purpose` | What the agent is for. Required |
| `brief.goal` | What a finished conversation looks like |
| `brief.howToAnswer` | Tone, wording and method. Name a tool, knowledge base, skill, agent or workflow with `@` |
| `brief.never` | Up to 20 hard rules. They are sent to the model last, before every reply |
| `brief.success` | Up to 8 lines kept for grading. They are not sent to the model |
| `patterns.thinking` | How hard the model thinks: `default`, `low`, `medium` or `high` |
| `patterns.parallelReads` | Whether read tools may run side by side. On by default |

| What you see | What it means |
|---|---|
| `promptMode` is `brief` | The instructions are written from the brief. Saving `instructions` on their own is refused with `brief_owns_prompt` |
| `publish_check` lists `missing_reference` | The brief mentions something the agent does not hold, and the field it is in. The agent cannot be published until you add it or remove the mention |
| `add_reference` returns an empty `added` | The agent already held it, and no new draft was saved |
| The publish request is `pending` | A brief with never rules is approved by a second person before it goes live |

## Next steps

- [Skill examples](skills.md): give the agent a reusable procedure.
- [Workflow examples](workflows.md): call this agent from a workflow step.
- [Agents](../agents.md): the agent lifecycle and the full list of example folders.
- [Python SDK](../../sdk/python.md) and [TypeScript SDK](../../sdk/typescript.md): every attribute and verb.
