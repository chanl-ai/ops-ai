# Only published skills are offered

Status: draft. Service: `agents-service`. Layers: api, mcp, ui.

In this example we will keep one skill as a draft and retire another, and see neither listed as a prompt nor served by name. Design case sk-chat-4; it fails today because the prompt list reads every skill and serves the newest draft.

| Use case | |
|---|---|
| Id | `uc-746` |
| Area | Agents |
| Design label | `sk-chat-4` |
| Runs | MCP; api and ui in their own scripts |
| Run it | `make usecase-test UC=uc-746` |

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

### 1. Make a draft skill and a retired skill

```python tab="MCP"
made = {}
for name, retire in (("Claims intake", False), ("Day-one checklist", True)):
    s = priya.raw.agents.agents_create_skill({"name": name, "ownerTeam": "team_ops", "useWhen": "Use for " + name, "instructions": "Do " + name})
    if retire:
        priya.raw.agents.agents_request_skill_publish(s["id"], {"note": "page"})
        priya.raw.agents.agents_deprecate_skill(s["id"], {"reason": "replaced"})
    made[name] = s["id"]
```

Expected: a skill with only a draft v1, and a retired one.

### 2. The prompt list holds neither

```python tab="MCP"
names = set(prompts())
assert not names & {"claims-intake", "day-one-checklist"}, names
```

Expected: neither name is listed.

### 3. Fetching the draft by name is refused

```python tab="MCP"
try:
    get_prompt("claims-intake", {})
    raise AssertionError("the draft was served")
except AssertionError:
    raise
except BaseException as exc:
    def leaves(e):
        return [x for sub in e.exceptions for x in leaves(sub)] if hasattr(e, "exceptions") else [e]
    assert any("no published skill" in str(e).lower() for e in leaves(exc)), leaves(exc)
```

Expected: refused.

## What proves it

Step 2 fails while the list includes a draft or a retired skill; step 3 fails while the newest draft is served.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, the Salesforce plugin and the team MCP address, a fake Salesforce signed in for the team, agents-service (MCP) |
