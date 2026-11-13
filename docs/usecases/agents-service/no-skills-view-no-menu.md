# Skills stay out of reach without the right

Status: draft. Service: `agents-service`. Layers: api, mcp (no ui script yet).

In this example we will see that a person who may chat but not view skills gets no list of them over MCP and no way to name one in a send. It assumes Dana holds the Chat role only. Design case sk-chat-3.

| Use case | |
|---|---|
| Id | `uc-745` |
| Area | Agents |
| Design label | `sk-chat-3` |
| Runs | MCP; api in its own script |
| Run it | `make usecase-test UC=uc-745` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |
| Dana, who may chat but not read skills | Chat user | the `dana` profile |

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

## Steps

### 1. The team's Salesforce skill has three parts

```python tab="MCP"
rows = priya.raw.agents.agents_list_skills()
made = next(s for s in (rows["data"] if isinstance(rows, dict) else rows) if s["name"] == "Salesforce")
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "client-brief", "update-opportunity"], parts
```

Expected: the team's Salesforce skill, installed from the Salesforce plugin, lists its three parts.

### 2. Dana's assistant lists no skill prompts

```python tab="MCP"
dana = json.load(open(os.environ["OPS_CONFIG"]))["profiles"]["dana"]
async def dana_prompts():
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {dana['mcpToken']}"}, timeout=30) as http,
        Client(streamable_http_client(dana["mcpUrl"], http_client=http), client_info=Implementation(name="assistant", version="1.0"), cache=None) as c,
    ):
        return [p.name for p in (await c.list_prompts()).prompts]
assert not [n for n in asyncio.run(dana_prompts()) if n.startswith("salesforce")]
```

Expected: no Salesforce prompt.

## What proves it

Step 2 fails while a person without Skills: view is offered a skill prompt.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service (MCP) |
