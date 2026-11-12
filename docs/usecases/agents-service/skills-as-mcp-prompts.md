# A team's skill is an assistant's prompt

Status: current. Service: `agents-service`. Layers: sdk (Python; see Gaps).

In this example we will install the starter skill "Doc co-authoring" and fetch it from the team's MCP address as a
prompt, with its inputs as the prompt's arguments. It assumes the starters pack is on for the team and the skill
declares the inputs `topic` and `doc_type`.

| Use case | |
|---|---|
| Id | `uc-742` |
| Area | Agents |
| Runs | Python |
| Run it | `make usecase-test UC=uc-742 LAYER=sdk` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Before you start

```python tab="Python" tab-group="language"
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
```

## Steps

### 1. Install the starter skill

```python tab="Python" tab-group="language"
assert priya.templates.install("plugin:opsai.starters:doc-coauthoring")["created"] is True
```

Expected: installed.

### 2. The assistant finds it in the prompt list

```python tab="Python" tab-group="language"
async def prompts():
    async with assistant() as c:
        return {p.name: p for p in (await c.list_prompts()).prompts}

found = asyncio.run(prompts())["doc-coauthoring"]
assert sorted(a.name for a in found.arguments) == ["doc_type", "topic"]
```

Expected: `doc-coauthoring` with arguments `topic` and `doc_type`.

### 3. The prompt returns the skill with the arguments filled in

```python tab="Python" tab-group="language"
async def get():
    async with assistant() as c:
        return await c.get_prompt("doc-coauthoring", {"topic": "Card dispute letters", "doc_type": "runbook"})

text = " ".join(getattr(m.content, "text", "") for m in asyncio.run(get()).messages)
assert "Card dispute letters" in text
```

Expected: the skill's instructions with the topic in them.

## Gaps

| Product fix | Step | What the TypeScript SDK and the command line cannot do |
|---|---|---|
| A TypeScript tab needs an MCP client in the repo's tooling, and `opsai` needs a command that reads the team's MCP prompts (`opsai mcp prompts`, `opsai mcp prompt`) | 2 to 3 | Neither tab can list or fetch a prompt on the team's MCP address; the page has Python tabs only |

## What proves it

Step 2 fails while a skill keeps no inputs; step 3 fails if the arguments are not substituted.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack and the team MCP address, agents-service |
| Older script | `docs/usecases/agents-service/scripts/test-uc-742-mcp.py` |
