# Prepare a client meeting from the slash menu

Status: draft. Service: `agents-service`. Layers: api, sdk, mcp, ui.

In this example we will use the team's Salesforce skill, which holds three parts, pick "Read a client" in a chat with Okafor Family Trust as the client, and see the same part offered to an assistant as a prompt. It assumes the team has an agent that may use team skills. Design case sk-chat-1.

| Use case | |
|---|---|
| Id | `uc-743` |
| Area | Agents |
| Design label | `sk-chat-1` |
| Runs | Python, TypeScript, MCP; api and ui in their own scripts |
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

priya = OpsAI(profile="priya")
```
```ts tab="TypeScript" tab-group="language"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const priya = new OpsAI({ profile: 'priya' });
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
const got = (await priya.raw.agents.agents_get_skill({ skill_id: made.id } as any)) as any;
assert.deepEqual((got.parts ?? []).map((p: any) => p.slug), ['prepare-meeting', 'client-brief', 'update-opportunity']);
```
```python tab="MCP"
rows = priya.raw.agents.agents_list_skills()
made = next(s for s in (rows["data"] if isinstance(rows, dict) else rows) if s["name"] == "Salesforce")
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "client-brief", "update-opportunity"], parts
```

Expected: the published version lists `prepare-meeting`, `client-brief` and `update-opportunity`.

### 2. Pick the part in a chat and send

```python tab="Python" tab-group="language"
agent = priya.agents.create({"name": "Desk", "role": "Answers the team", "model": next(iter(priya.raw.agents.agents_list_model_aliases()))["name"]})
priya.agents.publish(agent["id"], note="page", version=agent.get("draftVersion") or 1)
thread = priya.chat.start(agent["id"])["id"]
events = list(priya.chat.say(thread, "Prepare my meeting", skill=made["id"], part="client-brief", inputs={"client": "Okafor Family Trust"}))
reply = [m for m in priya.chat.get(thread)["messages"] if m["role"] == "assistant"][-1]
assert any(s["name"] == "Salesforce" and s["part"] == "client-brief" and s["how"] == "picked" for s in reply["skills"]), reply["skills"]
```
```ts tab="TypeScript" tab-group="language"
const agent = (await priya.agents.create({ name: 'Desk', role: 'Answers the team' } as any)) as any;
const thread = ((await (priya as any).chat.start(agent.id)) as any).id;
await (priya as any).chat.say(thread, 'Prepare my meeting', { skill: made.id, part: 'client-brief', inputs: { client: 'Okafor Family Trust' } });
const msgs = ((await (priya as any).chat.get(thread)) as any).messages;
const last = msgs.filter((m: any) => m.role === 'assistant').at(-1);
assert.ok(last.skills.some((s: any) => s.name === 'Salesforce' && s.part === 'client-brief' && s.how === 'picked'));
```

Expected: the reply records the skill, its version, the part and how: picked.

### 3. The assistant finds the part as a prompt and gets it filled in

```python tab="MCP"
found = prompts()["salesforce-client-brief"]
assert [a.name for a in found.arguments if a.required] == ["client"], found.arguments
text = " ".join(getattr(m.content, "text", "") for m in get_prompt("salesforce-client-brief", {"client": "Okafor Family Trust"}).messages)
assert "Okafor Family Trust" in text and "FROM Account" in text, text
```

Expected: the prompt `salesforce-client-brief` with `client` required; the part's text with the client in it.

## What proves it

Step 1 fails while a skill keeps no parts. Step 2 fails while a send cannot name a part. Step 3 fails while the prompt list holds whole skills only.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service (MCP) |
