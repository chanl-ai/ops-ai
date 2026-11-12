# A required input must be filled

Status: draft. Service: `agents-service`. Layers: api, mcp, ui.

In this example we will ask an assistant for the "Read a client" part with no Client and be refused with the input named. Design case sk-chat-5; it fails today because the prompt is served with `{{client}}` left in the text.

| Use case | |
|---|---|
| Id | `uc-747` |
| Area | Agents |
| Design label | `sk-chat-5` |
| Runs | MCP; api and ui in their own scripts |
| Run it | `make usecase-test UC=uc-747` |

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

## Steps

### 1. The team's Salesforce skill has three parts

```python tab="MCP"
rows = priya.raw.agents.agents_list_skills()
made = next(s for s in (rows["data"] if isinstance(rows, dict) else rows) if s["name"] == "Salesforce")
parts = [p["slug"] for p in (priya.raw.agents.agents_get_skill(made["id"]).get("parts") or [])]
assert parts == ["prepare-meeting", "client-brief", "update-opportunity"], parts
```

Expected: the team's Salesforce skill, installed from the Salesforce plugin, lists its three parts.

### 2. The prompt is refused without its required input

```python tab="MCP"
try:
    text = " ".join(getattr(m.content, "text", "") for m in get_prompt("salesforce-client-brief", {}).messages)
except BaseException as exc:
    def leaves(e):
        return [x for sub in e.exceptions for x in leaves(sub)] if hasattr(e, "exceptions") else [e]
    refusals = [e for e in leaves(exc) if "missing_input" in str(e)]
    assert refusals and "client" in str(refusals[0]).lower(), leaves(exc)
else:
    raise AssertionError("served with the input missing: " + text[:120])
```

Expected: refused, naming Client.

## What proves it

Step 2 fails while a missing required input leaves `{{client}}` in the served text.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service (MCP) |
