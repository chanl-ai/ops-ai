# Prepare a client meeting from the slash menu

Status: draft. Service: `agents-service`. Layers: api, sdk, mcp, ui.

In this example we will publish a Salesforce skill that holds two parts, pick "Prepare a client meeting" in a chat with Okafor Family Trust as the client, and see the same part offered to an assistant as a prompt. It assumes the team has an agent that may use team skills. Design case sk-chat-1.

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

### 1. Publish the Salesforce skill with two parts

```python tab="Python" tab-group="language"
PARTS = [
    {"slug": "prepare-meeting", "name": "Prepare a client meeting", "useWhen": "Use to brief the adviser before a client meeting.",
     "instructions": "Read the client's account and write a one-page brief.",
     "inputs": [{"name": "client", "description": "The client's name", "required": True}]},
    {"slug": "update-opportunity", "name": "Update an opportunity", "useWhen": "Use to change an opportunity after a client call.",
     "instructions": "Read the change back and ask for a confirmation before saving.",
     "inputs": [{"name": "client", "description": "The client's name", "required": True}]},
]
made = priya.raw.agents.agents_create_skill({"name": "Salesforce", "ownerTeam": "team_ops", "useWhen": "Use for a client's Salesforce record.",
                                              "instructions": "Work only from Salesforce.", "parts": PARTS})
skill = priya.raw.agents.agents_request_skill_publish(made["id"], {"note": "page"})
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "update-opportunity"], parts
```
```ts tab="TypeScript" tab-group="language"
const PARTS = [
  { slug: 'prepare-meeting', name: 'Prepare a client meeting', useWhen: 'Use to brief the adviser before a client meeting.',
    instructions: "Read the client's account and write a one-page brief.",
    inputs: [{ name: 'client', description: "The client's name", required: true }] },
  { slug: 'update-opportunity', name: 'Update an opportunity', useWhen: 'Use to change an opportunity after a client call.',
    instructions: 'Read the change back and ask for a confirmation before saving.',
    inputs: [{ name: 'client', description: "The client's name", required: true }] },
];
const made = (await priya.raw.agents.agents_create_skill({ body: { name: 'Salesforce', ownerTeam: 'team_ops', useWhen: "Use for a client's Salesforce record.", instructions: 'Work only from Salesforce.', parts: PARTS } as any })) as any;
await priya.raw.agents.agents_request_skill_publish({ skill_id: made.id, body: { note: 'page' } } as any);
const got = (await priya.raw.agents.agents_get_skill({ skill_id: made.id } as any)) as any;
assert.deepEqual((got.parts ?? []).map((p: any) => p.slug), ['prepare-meeting', 'update-opportunity']);
```
```python tab="MCP"
PARTS = [
    {"slug": "prepare-meeting", "name": "Prepare a client meeting", "useWhen": "Use to brief the adviser before a client meeting.",
     "instructions": "Read the client's account and write a one-page brief.",
     "inputs": [{"name": "client", "description": "The client's name", "required": True}]},
    {"slug": "update-opportunity", "name": "Update an opportunity", "useWhen": "Use to change an opportunity after a client call.",
     "instructions": "Read the change back and ask for a confirmation before saving.",
     "inputs": [{"name": "client", "description": "The client's name", "required": True}]},
]
made = priya.raw.agents.agents_create_skill({"name": "Salesforce", "ownerTeam": "team_ops", "useWhen": "Use for a client's Salesforce record.",
                                              "instructions": "Work only from Salesforce.", "parts": PARTS})
skill = priya.raw.agents.agents_request_skill_publish(made["id"], {"note": "page"})
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "update-opportunity"], parts
```

Expected: the published version lists `prepare-meeting` and `update-opportunity`.

### 2. Pick the part in a chat and send

```python tab="Python" tab-group="language"
agent = priya.agents.create({"name": "Desk", "role": "Answers the team", "model": next(iter(priya.raw.agents.agents_list_model_aliases()))["name"]})
priya.agents.publish(agent["id"], note="page", version=agent.get("draftVersion") or 1)
thread = priya.chat.start(agent["id"])["id"]
events = list(priya.chat.say(thread, "Prepare my meeting", skill=made["id"], part="prepare-meeting", inputs={"client": "Okafor Family Trust"}))
reply = [m for m in priya.chat.get(thread)["messages"] if m["role"] == "assistant"][-1]
assert any(s["name"] == "Salesforce" and s["part"] == "prepare-meeting" and s["how"] == "picked" for s in reply["skills"]), reply["skills"]
```
```ts tab="TypeScript" tab-group="language"
const agent = (await priya.agents.create({ name: 'Desk', role: 'Answers the team' } as any)) as any;
const thread = ((await (priya as any).chat.start(agent.id)) as any).id;
await (priya as any).chat.say(thread, 'Prepare my meeting', { skill: made.id, part: 'prepare-meeting', inputs: { client: 'Okafor Family Trust' } });
const msgs = ((await (priya as any).chat.get(thread)) as any).messages;
const last = msgs.filter((m: any) => m.role === 'assistant').at(-1);
assert.ok(last.skills.some((s: any) => s.name === 'Salesforce' && s.part === 'prepare-meeting' && s.how === 'picked'));
```

Expected: the reply records the skill, its version, the part and how: picked.

### 3. The assistant finds the part as a prompt and gets it filled in

```python tab="MCP"
found = prompts()["salesforce-prepare-meeting"]
assert [a.name for a in found.arguments if a.required] == ["client"], found.arguments
text = " ".join(getattr(m.content, "text", "") for m in get_prompt("salesforce-prepare-meeting", {"client": "Okafor Family Trust"}).messages)
assert "Okafor Family Trust" in text and "one-page brief" in text, text
```

Expected: the prompt `salesforce-prepare-meeting` with `client` required; the part's text with the client in it.

## What proves it

Step 1 fails while a skill keeps no parts. Step 2 fails while a send cannot name a part. Step 3 fails while the prompt list holds whole skills only.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack and the team MCP address, agents-service (MCP) |
