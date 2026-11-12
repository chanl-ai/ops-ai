# Chat with an agent

Status: draft for review.

In this example we will draft an IT help desk agent, give it a laptop lookup tool, test it, publish it, and have a colleague chat with it. It assumes a signed-in builder and a signed-in member in the same team, and a model that calls the lookup when asked about a device.

| Use case | |
|---|---|
| Id | `uc-018` |
| Area | Agents |
| Runs | Python, TypeScript, CLI; console steps in their own script |
| Run it | `make usecase-test UC=uc-018` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The help desk lead who builds the agent | Builder | the `builder` profile |
| A colleague who asks it about a laptop | Member | the `member` profile |

The run starts the agents service on a scripted model: it calls `lookup_device` when asked about a device and answers
"I could not find that." when it has no tool to call. No model provider is called.

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI
from ops_ai.errors import BadRequest
import pytest

builder = OpsAI(profile="builder")
colleague = OpsAI(profile="member")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const builder = new OpsAI({ profile: 'builder' });
const colleague = new OpsAI({ profile: 'member' });
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=builder
cat > laptop-helper.yaml <<'YAML'
name: Laptop helper
role: Answers questions about a person's laptop
model: help-desk-standard
instructions: Look up the device before you answer.
YAML
```

## Steps

### 1. Draft the agent

```python tab="Python" tab-group="language"
agent = builder.agents.apply({
    "name": "Laptop helper",
    "role": "Answers questions about a person's laptop",
    "model": "help-desk-standard",
    "instructions": "Look up the device before you answer.",
})
assert agent["availability"] == "not_published"
```

```ts tab="TypeScript"
const agent = await builder.agents.apply({
  name: 'Laptop helper',
  role: "Answers questions about a person's laptop",
  model: 'help-desk-standard',
  instructions: 'Look up the device before you answer.',
});
assert.equal(agent.availability, 'not_published');
```

```bash tab="CLI"
AGENT=$(opsai agents --json apply laptop-helper.yaml | jq -r .id)
opsai agents --json export "$AGENT" | jq -e '.availability == "not_published"'
```

Expected: a draft at version 1 that nobody can chat with yet.

### 2. A chat with the draft is refused

```python tab="Python" tab-group="language"
with pytest.raises(BadRequest) as refused:
    colleague.agents.chat(agent["id"], "Is laptop LT-2291 under warranty?")
assert refused.value.code == "agent_not_published"
```

```ts tab="TypeScript"
await assert.rejects(colleague.agents.chat(agent.id, 'Is laptop LT-2291 under warranty?'), {
  code: 'agent_not_published',
});
```

```bash tab="CLI"
if refused=$(opsai agents --profile member chat "$AGENT" --message "Is laptop LT-2291 under warranty?" 2>&1); then exit 1; fi
grep -q '^agent_not_published:' <<<"$refused"
```

Expected: refused, because a draft is not live.

### 3. Give it the lookup tool and test it

```python tab="Python" tab-group="language"
agent = builder.agents.apply({"name": "Laptop helper", "tools": ["lookup_device"]})
assert agent["version"] == 2 and agent["publishedVersion"] is None

turn = builder.agents.test(agent["id"], "Is laptop LT-2291 under warranty?")
assert [call["name"] for call in turn["toolCalls"]] == ["lookup_device"]
assert turn["model"] == "help-desk-standard"
```

```ts tab="TypeScript"
const granted = await builder.agents.apply({ name: 'Laptop helper', tools: ['lookup_device'] });
assert.equal(granted.version, 2);
assert.equal(granted.publishedVersion, null);

const turn = await builder.agents.test(granted.id, 'Is laptop LT-2291 under warranty?');
assert.deepEqual(turn.toolCalls.map((call: { name: string }) => call.name), ['lookup_device']);
assert.equal(turn.model, 'help-desk-standard');
```

```bash tab="CLI"
echo "tools: [lookup_device]" >> laptop-helper.yaml
opsai agents --json apply laptop-helper.yaml | jq -e '.version == 2 and .publishedVersion == null'
opsai agents --json test "$AGENT" --message "Is laptop LT-2291 under warranty?" \
  | jq -e '[.toolCalls[].name] == ["lookup_device"] and .model == "help-desk-standard"'
```

Expected: version 2 with the tool, still unpublished; the test turn calls `lookup_device` on the agent's model.

### 4. Publish it

```python tab="Python" tab-group="language"
review = builder.agents.publish(agent["id"], note="Ready for the help desk", version=2)
assert review["kind"] == "agent_publish" and review["status"] == "approved"
```

```ts tab="TypeScript"
const review = await builder.agents.publish(agent.id, 'Ready for the help desk', 2);
assert.equal(review.kind, 'agent_publish');
assert.equal(review.status, 'approved');
```

```bash tab="CLI"
opsai agents --json publish "$AGENT" --note "Ready for the help desk" \
  | jq -e '.kind == "agent_publish" and .status == "approved"'
```

Expected: a publish review, approved at once because the run's team approves its own publishes.

### 5. A colleague's chat is answered after the lookup

```python tab="Python" tab-group="language"
reply = colleague.agents.chat(agent["id"], "Is laptop LT-2291 under warranty?")
assert [call["name"] for call in reply["toolCalls"]] == ["lookup_device"]
assert reply["text"] == "Here is what I found."
```

```ts tab="TypeScript"
const reply = await colleague.agents.chat(agent.id, 'Is laptop LT-2291 under warranty?');
assert.deepEqual(reply.toolCalls.map((call: { name: string }) => call.name), ['lookup_device']);
assert.equal(reply.text, 'Here is what I found.');
```

```bash tab="CLI"
opsai agents --profile member --json chat "$AGENT" --message "Is laptop LT-2291 under warranty?" \
  | jq -e '[.toolCalls[].name] == ["lookup_device"] and .text == "Here is what I found."'
```

Expected: the reply comes after `lookup_device` returns.

## Gaps

This page does not pass while a row here is open. Each open gap is a product change tracked on its own; no test helper stands in for it.

| Product fix | Step | Tab | What is missing | Where |
|---|---|---|---|---|
| The TypeScript SDK reads the saved profile | All | TypeScript | `new OpsAI({ profile })` cannot read the saved sign-in profile | `sdk/typescript/src/client.ts:257-263` |
| `opsai agents` takes options after the verb | All | CLI | `--json` and `--profile` are accepted only before the verb | `sdk/python/src/ops_ai/_cli/agents.py:15-38` |

## What proves it

> [!IMPORTANT]
> Steps 2 and 5 make the same chat call. It is refused before the publish and answered after it, so the answer is the
> publish's doing. Without the tool granted in step 3 the scripted model answers "I could not find that." and step 5
> fails.

## In the console

| # | Step | Expected |
|---|---|---|
| 1 | Agents, New agent, a name and a role | The agent page opens; the header says Not published |
| 2 | Tools, tick `lookup_device`, save | Version 2 |
| 3 | Request publish with a note | The header drops Request publish |
| 4 | Chat with the agent | The reply shows the tool ran |

## Details

| | |
|---|---|
| Services the run starts | platform, agents and models services on the scripted model |
| Console script | `docs/usecases/agents/scripts/test-uc-018-ui.mjs`, moved here from `agents-service` when this page converts |
| Replaces | `test-uc-018-api.py`, deleted when this page passes |
