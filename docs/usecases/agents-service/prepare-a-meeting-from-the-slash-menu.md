# Prepare a client meeting from the slash menu

Status: draft. Service: `agents-service`. Layers: api, sdk, cli, mcp, ui.

In this example we will use the team's Salesforce skill, which holds three parts, pick "Read a client" in a chat with Okafor Family Trust as the client, and see the same part offered to an assistant as a prompt. It assumes the team has an agent that may use team skills. Design case sk-chat-1.

| Use case | |
|---|---|
| Id | `uc-743` |
| Area | Agents |
| Design label | `sk-chat-1` |
| Runs | Python, TypeScript, CLI, MCP; api and ui in their own scripts |
| Run it | `make usecase-test UC=uc-743` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Before you start

```python tab="MCP"
import asyncio
import json
import os
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from ops_ai import OpsAI

profile = json.load(open(os.environ["OPS_CONFIG"]))["profiles"]["priya"]
priya = OpsAI(profile="priya")


@asynccontextmanager
async def assistant():
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {profile['mcpToken']}"}, timeout=30) as http,
        Client(streamable_http_client(profile["mcpUrl"], http_client=http), client_info=Implementation(name="assistant", version="1.0"), cache=None) as c,
    ):
        yield c


def prompts():
    async def go():
        async with assistant() as c:
            return {p.name: p for p in (await c.list_prompts()).prompts}
    return asyncio.run(go())


def get_prompt(name, args):
    async def go():
        async with assistant() as c:
            return await c.get_prompt(name, args)
    return asyncio.run(go())
```


```python tab="Python" tab-group="language"
from ops_ai import OpsAI
from steps import publish_agent

priya = OpsAI(profile="priya")
SALESFORCE_TOOLS = ["salesforce_search", "salesforce_query", "salesforce_get_record", "salesforce_field_values", "salesforce_save_records"]
```
```ts tab="TypeScript" tab-group="language"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';
import { publishAgent } from '@ops-ai/usecase-runner/steps';

const SALESFORCE_TOOLS = ['salesforce_search', 'salesforce_query', 'salesforce_get_record', 'salesforce_field_values', 'salesforce_save_records'];
const priya = new OpsAI({ profile: 'priya' });
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=priya
```

## Steps

### 1. The team's Salesforce skill has three parts

```python tab="Python" tab-group="language"
rows = priya.raw.agents.agents_list_skills()
made = next(s for s in (rows["data"] if isinstance(rows, dict) else rows) if s["name"] == "Salesforce")
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "client-brief", "update-opportunity"], parts
```
```ts tab="TypeScript" tab-group="language"
const rows = (await priya.raw.agents.agents_list_skills()) as any;
const made = (Array.isArray(rows) ? rows : rows.data).find((s: any) => s.name === 'Salesforce');
const got = (await priya.raw.agents.agents_get_skill({ path: { skill_id: made.id } } as any)) as any;
assert.deepEqual((got.parts ?? []).map((p: any) => p.slug), ['prepare-meeting', 'client-brief', 'update-opportunity']);
```
```python tab="MCP"
rows = priya.raw.agents.agents_list_skills()
made = next(s for s in (rows["data"] if isinstance(rows, dict) else rows) if s["name"] == "Salesforce")
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "client-brief", "update-opportunity"], parts
```
```bash tab="CLI"
opsai resources --json list plugin:opsai.salesforce \
  | jq -e 'any(.[]; .kind == "skill" and .title == "Salesforce" and .state == "added")'
```

Expected: the published version lists `prepare-meeting`, `client-brief` and `update-opportunity`. On the command line the team's Salesforce skill is listed as added; `opsai` has no command that shows a skill's parts, so step 2 picks one by name.

### 2. Pick the part in a chat and send

```python tab="Python" tab-group="language"
agent_id, _ = publish_agent(priya, "Desk", role="Answers the team", tool_ids=SALESFORCE_TOOLS)
thread = priya.chat.start(agent_id)["id"]
events = list(priya.chat.say(thread, "Prepare my meeting", skill=made["id"], part="client-brief", inputs={"client": "Okafor Family Trust"}))
reply = [m for m in priya.chat.get(thread)["messages"] if m["role"] == "assistant"][-1]
assert any(s["name"] == "Salesforce" and s["part"] == "client-brief" and s["how"] == "picked" for s in reply["skills"]), reply["skills"]
```
```ts tab="TypeScript" tab-group="language"
const { agentId } = await publishAgent(priya, { name: 'Desk', role: 'Answers the team', toolIds: SALESFORCE_TOOLS });
const thread = ((await (priya as any).chat.start(agentId)) as any).id;
await (priya as any).chat.say(thread, 'Prepare my meeting', { skill: made.id, part: 'client-brief', inputs: { client: 'Okafor Family Trust' } });
const msgs = ((await (priya as any).chat.get(thread)) as any).messages;
const last = msgs.filter((m: any) => m.role === 'assistant').at(-1);
assert.ok(last.skills.some((s: any) => s.name === 'Salesforce' && s.part === 'client-brief' && s.how === 'picked'));
```

```bash tab="CLI"
cat > desk.yaml <<'YAML'
name: Desk
role: Answers the team
YAML
AGENT=$(opsai agents --json apply desk.yaml | jq -r .id)
opsai agents grant-tools "$AGENT" salesforce_search salesforce_query salesforce_get_record salesforce_field_values salesforce_save_records >/dev/null
opsai agents --json publish "$AGENT" --note "Ready" >/dev/null
THREAD=$(opsai chat say --agent Desk --skill Salesforce/client-brief --input client="Okafor Family Trust" \
  -m "Prepare my meeting" --json | jq -r .thread)
opsai chat show "$THREAD" --json | jq -e '[.messages[] | select(.role == "assistant")] | last | .skills
  | any(.name == "Salesforce" and .part == "client-brief" and .how == "picked")'
```

Expected: the reply records the skill, its version, the part and how: picked.

```python tab="MCP"
text = " ".join(getattr(m.content, "text", "") for m in get_prompt("salesforce-client-brief", {"client": "Okafor Family Trust"}).messages)
assert "Okafor Family Trust" in text, text
```

Expected: the part is served with the client filled in, the same text a picked part sends.

### 3. The assistant finds the part as a prompt and gets it filled in

```python tab="Python" tab-group="language"
part = next(p for p in priya.raw.agents.agents_get_skill(made["id"])["parts"] if p["slug"] == "client-brief")
assert [i["name"] for i in part["inputs"] if i.get("required")] == ["client"], part["inputs"]
```
```ts tab="TypeScript" tab-group="language"
const brief = (got.parts as any[]).find((p) => p.slug === 'client-brief');
assert.deepEqual(brief.inputs.filter((i: any) => i.required).map((i: any) => i.name), ['client']);
```
```python tab="MCP"
found = prompts()["salesforce-client-brief"]
assert [a.name for a in found.arguments if a.required] == ["client"], found.arguments
text = " ".join(getattr(m.content, "text", "") for m in get_prompt("salesforce-client-brief", {"client": "Okafor Family Trust"}).messages)
assert "Okafor Family Trust" in text and "FROM Account" in text, text
```
```bash tab="CLI"
if refused=$(opsai chat say --thread "$THREAD" --skill Salesforce/client-brief -m "Prepare my meeting" 2>&1); then exit 1; fi
grep -qi 'client' <<<"$refused"
grep -q 'missing_input' <<<"$refused"
```

Expected: the prompt `salesforce-client-brief` with `client` required; the part's text with the client in it. The SDK tabs read the same part from the skill: `client` required.

## What proves it

Step 1 fails while a skill keeps no parts. Step 2 fails while a send cannot name a part. Step 3 fails while the prompt list holds whole skills only.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service (MCP) |
