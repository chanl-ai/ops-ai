# Agent examples

Status: current.

Your team asks the same questions every day, and the answers sit in policy documents that few people read. You want
an agent that answers them in a chat, from your own documents, and that a second person has reviewed before anyone
relies on it.

If you build that agent by hand in the console and never write it down, the next person to change it has no record to
work from. Nobody can say what changed, and nobody can set up the same agent in another team. These examples keep the
agent in a file or a few lines of code, so your team can review a change to it the way it reviews any other change.

## The plan

<!-- site: steps -->
1. **Create and publish the agent.** One file or a few lines of code, then a publish request.
2. **Chat with it**, and keep the conversation going with a follow-up.
3. **Give it your documents**, so its answers cite the page they came from.
4. **Grant it a tool**, if it needs to look something up or open a case.
5. **Test the draft and score it** before a change reaches anyone.

Connect first: see [Connect once, then copy any example](README.md#connect-once-then-copy-any-example). Each example
carries on from the one before it.

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
| Score with cases | built | built | built |
| Write the agent as a brief, check what blocks a publish, add what the brief mentions | upcoming | upcoming | upcoming |

## Put an agent your team can chat with into a file

Every agent starts here. People chat with the published version, so your edits reach them only after you publish.
Because the definition lives in a file or a few lines of code, a change to it can be reviewed like any other change.

<!-- site: state caption="An agent's draft reaches people only after a publish request is approved" -->
- **Draft**: Your edits, which nobody chats with
  - **Publish requested**: You send a publish request
- **Publish requested**: Your team's publish policy decides whether a reviewer is needed
  - **Published**: A reviewer approves. A first publish needs one, and the person who asked cannot approve it
- **Published**: People chat with this version

In Python, `apply` creates the agent, or updates the draft of the agent that already has this name.

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

In TypeScript, `apply` creates a new agent each time you call it, so call it once and keep the id.

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

On the command line, you describe the agent in a YAML or JSON file.

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
status, which is `approved` when no reviewer is needed.

## Ask a question and follow up in the same conversation

Once the agent is published, you can ask it a question from a script and then ask a follow-up in the same
conversation. This makes a quick check after a publish, and the same calls serve any program that talks to an agent
on a person's behalf.

```python
first = ops.agents.chat(agent["id"], "Can I return shoes after two weeks?")
print(first["reply"])

again = ops.agents.chat(agent["id"], "And without a receipt?", thread_id=first["threadId"])
print(again["reply"])
```

In TypeScript, `ops.chat` opens a conversation and returns the events of each reply. The last event carries the
whole message.

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

## Make the agent answer from your policy pages

Your agent should answer from your policy pages and show which page each answer came from. If you paste policy text
into the instructions, nobody can see which part of it an answer used. Put the text in a knowledge base instead
whenever answers must come from text your team owns and keeps up to date.

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

In TypeScript, `apply` creates a new agent, so add the knowledge base to the existing one with `update`.

```ts
const base = await ops.knowledge.addBase('Store policies (TypeScript)', { owner: 'returns.lead@example.com' });
await ops.knowledge.addPage(base.id, 'Returns', 'Items can be returned within 30 days with a receipt. Sale items are final.');

await ops.agents.update(agent.id, { collections: [base.id] });
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

Every knowledge base needs an owner, the person who answers for what it serves. If you save a page under a title that
already exists, it is stored as a new version of that page.

## Let the agent open a case

When a reply needs live data, or needs to change something such as opening a case, grant the agent a tool. An agent
can only be granted tools your team has published. A grant changes the agent's draft, so publish again before the tool
takes effect.

```python
for option in ops.agents.tool_options("case"):
    print(option["id"], option["label"])

ops.agents.grant_tools(agent["id"], ["open_case"])  # use an id the loop above printed
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
(`workflow:<id>`). `grant_tools` adds to the tools the agent already holds. If your team's policy says that changes
must wait for approval, a tool that changes something pauses the reply until a person approves the call.

## Try a change before anyone sees it

After you change the draft, you can see how it answers before the change reaches anyone. Run this test between
`apply` and `publish`.

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

The result holds the reply together with what produced it: the model, whether knowledge was searched, the tool calls, the
skills and guardrails that applied, and the time it took.

## Start a long reply and read it later

A long reply does not have to hold your program up. You can start the agent, carry on, and read the conversation
later. Choose `wait` when your script needs the reply, `stream` when you want every event, and `background` when your
program has other work to do while the agent replies.

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

A background run is carried by the program that started it, so keep that program running until the reply is on the
thread. A script that exits straight after the call loses the run. The command line loses it too, because it exits as
soon as it has printed the ids. Runs that carry on without the caller are upcoming.

## Check that a change keeps your answers right

Before you publish a change to instructions, knowledge or tools, check that it has not broken the answers you care
about. Each case pairs an input with the checks its reply must pass.

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
| `judge` | A model judges the reply against a `rubric` you write |

The summary gives the number of cases that passed, the total, and the regressions. A regression is a case that the
published version passes and the draft fails.

## What success looks like

You have an agent id, a published version that answers from your documents with the page it used, and a draft you can
change and test without anyone else seeing it. Any teammate can pick the agent in the console's chat.

## What skipping the checks costs

If you publish an agent without a test turn or a scored case, your team gets whatever the last edit produced. A wrong
answer about a payoff period or a return window is then often found by a customer first, and nothing records which
change caused it.

## Upcoming: write what the agent is for, and what it must never do

> [!NOTE]
> **Upcoming.** This section is merged and is not in the current release (v1.0.0). Its examples were run against
> the merged code.

One long block of instructions mixes what the agent is for, how it should answer and what it must never do, and a
reviewer cannot tell which line is a hard rule. A brief keeps these apart, and it is the way to start a new agent.
The platform writes the agent's instructions from the brief, and sends the never rules to the model again before
every reply. An agent saved without a brief keeps working from its instructions as before.

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

In TypeScript, pass the same fields as an object.

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

The publish check also covers the agent's evals. Only a run of that exact version, on its content as it reads now,
counts. A draft keeps its version number while it is edited, so any save after a run means the agent needs a new run.
Until then the check answers `eval_not_run` (the agent changed since its last run), whatever the team's setting.

The check can also report these eval problems:

- `eval_failed`: a blocking step failed on the newest counted run, and the publish is refused. Approving a request
  whose version failed after the request opened is refused the same way, with 422 `cannot_publish` and the problems in
  `details.problems`.
- `eval_no_cases`: the team's "Require passing evals to publish" setting (`evalsRequired`) is on, and the agent has no
  saved cases.
- `eval_not_run`: the same setting is on, and there is no run on the version.
- `eval_setting_unread`: the setting cannot be read.

`opsai agents eval` runs the saved cases on the newest version and keeps the run. It prints one line per case, with
the judge's reason when a judge check failed, followed by the pass rate, the regressions, the cost and each step of the
publish gate. Its exit code is meant for CI:

- 0 when the gate is open.
- 1 when a blocking step failed.
- 2 when the run could not happen (no model, agent not found, or not allowed).

With `--cases FILE`, the command scores the cases in the file and keeps nothing. It then exits 0 when every case
passes, and 1 when any case fails.

```bash
opsai agents eval "$AGENT" || exit 1
```

```python
run = ops.agents.eval(agent["id"])                  # the saved cases; the run is kept
print(run["gate"]["blocked"], run["costUsd"])
ops.agents.eval_runs(agent["id"])                   # kept runs, newest first, without results
ops.agents.eval_run(run["id"])                      # one run with its case results
```

In TypeScript these are `ops.agents.eval(id)`, `evalCases`, `addEvalCases`, `evalRuns` and `evalRun`.

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
| The publish request is `pending` | A brief with never rules is approved by a second person before it goes live, except on a development stack that approves at once |

## What to do next

- [Skill examples](skills.md): give the agent a reusable procedure.
- [Workflow examples](workflows.md): call this agent from a workflow step.
- [Agents](../agents.md): the agent lifecycle and the full list of example folders.
- [Python SDK](../../sdk/python.md) and [TypeScript SDK](../../sdk/typescript.md): every attribute and verb.
